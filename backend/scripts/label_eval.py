"""Scores the live AI layer against hand-written labels in evals/messages.jsonl.

Run from backend/ (spends live Gemini calls; never runs under pytest):
    uv run --env-file <path to .env> python -m scripts.label_eval --budget 45
    uv run --env-file <path to .env> python -m scripts.label_eval --only <case id> ...

Labels were written before the first run. Results are merged by case id into evals/results.json
(so a rerun of a few cases keeps the rest), and docs/ai-eval.md is regenerated from that file.
Reply drafting is skipped (the code template is used), so only the classification and extraction
stage is measured. Case text is never printed; output shows ids and decisions only.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agent import llm
from app.agent.intake import analyze_intake
from app.agent.scope_guard import run_live_guard
from app.config import get_settings
from app.schemas.ai import IntakeAnalysis, LLMUnavailableError, ScopeGuardResult
from scripts.ai_eval import TODAY, EvalStopped, MeteredProvider
from tests.fixtures.ai_demo import DEMO_RATE_CARD, demo_scope

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "evals" / "messages.jsonl"
RESULTS_FILE = ROOT / "evals" / "results.json"
REPORT_FILE = ROOT.parent / "docs" / "ai-eval.md"

Expectation = dict[str, Any]


def load_cases(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _check(name: str, expected: Any, actual: Any, ok: bool) -> Expectation:
    return {"name": name, "ok": bool(ok), "expected": expected, "actual": actual}


def score_intake(result: IntakeAnalysis, expect: dict[str, Any]) -> list[Expectation]:
    out: list[Expectation] = []
    if "source_language" in expect:
        out.append(
            _check(
                "source_language",
                expect["source_language"],
                result.source_language,
                result.source_language == expect["source_language"],
            )
        )
    for field, wanted in expect.get("fields", {}).items():
        got = getattr(result, field)
        if "value" in wanted:
            out.append(
                _check(f"{field}.value", wanted["value"], got.value, got.value == wanted["value"])
            )
        if "value_not_in" in wanted:
            seen = (got.value or "").strip().lower()
            out.append(
                _check(
                    f"{field}.value not in",
                    wanted["value_not_in"],
                    got.value,
                    seen not in wanted["value_not_in"],
                )
            )
        if "provenance" in wanted:
            out.append(
                _check(
                    f"{field}.provenance",
                    wanted["provenance"],
                    got.provenance,
                    got.provenance == wanted["provenance"],
                )
            )
        if "needs_confirmation" in wanted:
            out.append(
                _check(
                    f"{field}.needs_confirmation",
                    wanted["needs_confirmation"],
                    got.needs_confirmation,
                    got.needs_confirmation == wanted["needs_confirmation"],
                )
            )
    if "budget_minor_units" in expect:
        out.append(
            _check(
                "budget_minor_units",
                expect["budget_minor_units"],
                result.budget_minor_units,
                result.budget_minor_units == expect["budget_minor_units"],
            )
        )
    if "budget_minor_units_in" in expect:
        out.append(
            _check(
                "budget_minor_units",
                expect["budget_minor_units_in"],
                result.budget_minor_units,
                result.budget_minor_units in expect["budget_minor_units_in"],
            )
        )
    formats = " ".join((f.value or "").lower() for f in result.file_formats)
    for word in expect.get("formats_include", []):
        out.append(_check(f"file_formats include {word}", True, word in formats, word in formats))
    for word in expect.get("formats_exclude", []):
        out.append(
            _check(f"file_formats exclude {word}", True, word not in formats, word not in formats)
        )
    return out


def _find_item(result: ScopeGuardResult, keywords: list[str]) -> Any:
    for item in result.items:
        text = f"{item.quote} {item.request_summary}".lower()
        if any(keyword.lower() in text for keyword in keywords):
            return item
    return None


def score_guard(result: ScopeGuardResult, expect: dict[str, Any]) -> list[Expectation]:
    out: list[Expectation] = []
    for wanted in expect["items"]:
        label = wanted["match"][0]
        item = _find_item(result, wanted["match"])
        if item is None:
            for key in ("classification", "rate_card_code", "billable", "amount"):
                out.append(_check(f"{label}.{key}", wanted[key], "no matching item", False))
            continue
        out.append(
            _check(
                f"{label}.classification",
                wanted["classification"],
                item.classification,
                item.classification == wanted["classification"],
            )
        )
        out.append(
            _check(
                f"{label}.rate_card_code",
                wanted["rate_card_code"],
                item.rate_card_code,
                item.rate_card_code == wanted["rate_card_code"],
            )
        )
        out.append(
            _check(
                f"{label}.billable",
                wanted["billable"],
                item.billable,
                item.billable == wanted["billable"],
            )
        )
        out.append(
            _check(
                f"{label}.amount",
                wanted["amount"],
                item.amount_minor_units,
                item.amount_minor_units == wanted["amount"],
            )
        )
    out.append(
        _check(
            "total",
            expect["total"],
            result.total_minor_units,
            result.total_minor_units == expect["total"],
        )
    )
    return out


class LoggedProvider(MeteredProvider):
    """Records each real HTTP attempt with the model and outcome so a case can report them."""

    def __init__(self, inner: llm.LLMProvider, *, budget: int, spacing: float) -> None:
        super().__init__(inner, budget=budget, spacing=spacing)
        self.skip_replies = True
        self.attempts: list[str] = []

    async def generate(
        self, *, model: str, system: str, user: str, response_schema: dict[str, Any]
    ) -> str:
        before = dict(self.outcomes)
        try:
            return await super().generate(
                model=model, system=system, user=user, response_schema=response_schema
            )
        finally:
            for key, count in self.outcomes.items():
                if count > before.get(key, 0):
                    self.attempts.append(key)


async def run_case(case: dict[str, Any], provider: LoggedProvider) -> dict[str, Any]:
    provider.attempts = []
    record: dict[str, Any] = {
        "id": case["id"],
        "kind": case["kind"],
        "language": case["language"],
        "tags": case["tags"],
        "run_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    try:
        if case["kind"] == "intake":
            result: IntakeAnalysis | ScopeGuardResult = await analyze_intake(
                case["message"], today=TODAY
            )
            expectations = score_intake(result, case["expect"])  # type: ignore[arg-type]
        else:
            scope = demo_scope(revisions_used=case["scope"]["revisions_used"])
            run = await run_live_guard(
                case["message"], scope=scope, rate_card=DEMO_RATE_CARD, today=TODAY
            )
            result = run.result
            expectations = score_guard(result, case["expect"])  # type: ignore[arg-type]
        record["source"] = result.source
        record["model_id"] = result.model_id
        record["expectations"] = expectations
        if result.source != "live":
            record["note"] = "cached result served, not a live call"
    except LLMUnavailableError:
        record.update(source="none", model_id=None, expectations=[], error="every model failed")
    record["attempts"] = list(provider.attempts)
    return record


def case_passed(record: dict[str, Any]) -> bool:
    return bool(record["expectations"]) and all(e["ok"] for e in record["expectations"])


def render_report(records: list[dict[str, Any]], total_calls: int) -> str:
    total = sum(len(r["expectations"]) for r in records)
    passed = sum(e["ok"] for r in records for e in r["expectations"])
    cases_ok = sum(case_passed(r) for r in records)
    lines = [
        "# AI evaluation",
        "",
        "Generated by `backend/scripts/label_eval.py` from `backend/evals/messages.jsonl` "
        "(labels written before the first run) and `backend/evals/results.json`. Written "
        "analysis below the generated part is by hand.",
        "",
        "## Result",
        "",
        f"- Cases: {len(records)} ({sum(r['kind'] == 'intake' for r in records)} intake, "
        f"{sum(r['kind'] == 'guard' for r in records)} Scope Guard), English and Korean.",
        f"- Expectations passed: **{passed} of {total} ({100 * passed / total:.0f}%)**."
        if total
        else "- No expectations scored.",
        f"- Cases with every expectation passed: **{cases_ok} of {len(records)}**.",
        f"- Live model calls spent in the recorded runs: {total_calls} (HTTP attempts, including "
        "failed ones).",
        "- Reply drafting was skipped, so replies come from the code template. This measures "
        "extraction and classification only, not reply prose.",
        "",
        "## Per case",
        "",
        "| Case | Lang | Source | Model attempts | Run | Passed | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in records:
        ok = sum(e["ok"] for e in r["expectations"])
        attempts = ", ".join(r.get("attempts", [])) or "none"
        status = "PASS" if case_passed(r) else "FAIL"
        lines.append(
            f"| `{r['id']}` | {r['language']} | {r['source']} | {attempts} | {r['run_at']} | "
            f"{ok}/{len(r['expectations'])} | {status} |"
        )
    lines += ["", "## Every expectation", ""]
    for r in records:
        lines.append(f"### `{r['id']}`")
        lines.append("")
        if r.get("error"):
            lines += [f"Error: {r['error']}. Nothing could be scored.", ""]
        for e in r["expectations"]:
            lines.append(
                f"- {'PASS' if e['ok'] else '**FAIL**'} `{e['name']}`: "
                f"expected `{json.dumps(e['expected'], ensure_ascii=False)}`, "
                f"got `{json.dumps(e['actual'], ensure_ascii=False)}`"
            )
        lines.append("")
    return "\n".join(lines)


def merge_results(old: dict[str, Any], new: list[dict[str, Any]], calls: int) -> dict[str, Any]:
    records = {r["id"]: r for r in old.get("records", [])}
    for record in new:
        records[record["id"]] = record
    return {"records": list(records.values()), "total_calls": old.get("total_calls", 0) + calls}


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    key = settings.llm_api_key.get_secret_value()
    if settings.llm_provider.strip().lower() not in ("", "gemini") or not key:
        print("A Gemini LLM_API_KEY is required.")
        return 2
    provider = LoggedProvider(llm.GeminiProvider(key), budget=args.budget, spacing=args.spacing)
    llm.set_provider(provider)
    print(f"Model chain: {llm.model_chain()}; budget: {args.budget} calls")
    cases = [c for c in load_cases() if not args.only or c["id"] in args.only]
    done: list[dict[str, Any]] = []
    stopped = None
    for case in cases:
        try:
            record = await run_case(case, provider)
        except EvalStopped as exc:
            stopped = str(exc)
            print(f"STOPPED: {stopped}")
            break
        done.append(record)
        ok = sum(e["ok"] for e in record["expectations"])
        print(f"{record['id']}: {ok}/{len(record['expectations'])} source={record['source']}")
        for e in record["expectations"]:
            if not e["ok"]:
                print(f"  FAIL {e['name']}: expected {e['expected']!r}, got {e['actual']!r}")
    old = json.loads(RESULTS_FILE.read_text()) if RESULTS_FILE.exists() else {}
    merged = merge_results(old, done, provider.calls)
    RESULTS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    generated = render_report(merged["records"], merged["total_calls"])
    existing = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else ""
    marker = "<!-- analysis -->"
    tail = existing[existing.index(marker) :] if marker in existing else marker + "\n"
    REPORT_FILE.write_text(generated + "\n" + tail, encoding="utf-8")
    print(f"Calls this run: {provider.calls}; outcomes: {provider.outcomes}")
    return 1 if stopped else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=45, help="Maximum live calls this run")
    parser.add_argument("--spacing", type=float, default=5.0, help="Seconds between calls")
    parser.add_argument("--only", nargs="*", help="Case ids to run")
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(main(parser.parse_args())))
