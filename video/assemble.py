"""Turn raw footage + narration into out/creator-milestone-demo.mp4.

    uv run python assemble.py

Per shot: slice and normalise the footage to 1920x1080 at 30 fps (idle waits shortened, cuts removed),
fit it to the shot window (speed up at most 1.5x, with a visible label), overlay the sandbox label, the
on-screen text and the captions, and pad the narration to the shot length. Shots are concatenated, a 2 s
end card is added, and the audio is encoded once as AAC. No music.

Also writes out/creator-milestone-demo-softsubs.mp4 (same video without burned captions, SRT as a
mov_text track), out/captions.srt (retimed to this cut, for YouTube) and out/timeline.json.
"""

import json
import shutil
import wave
from pathlib import Path

from cards import (caption, end_card, lower_third, phone_background, placeholder_card, s9_card,
                   static_overlay, tag)
from common import (FPS, OUT, RAW, SHOT_TEXT, duration, ensure_dirs, frame_ceil, need, parse_narration,
                    parse_srt, parse_timing, run)

SHOTS = [f"S{i}" for i in range(1, 10)]
MAX_SPEED = 1.5
IDLE_KEEP = 0.5  # seconds of an idle wait that stay in, under a "Wait cut" tag
TAIL = 0.5  # silence after the narration ends
END_CARD = 2.0
LIMIT = 170.0
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", "60",
       "-bf", "2", "-an"]


def merge(spans: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def prepare_footage(seg: dict, dest: Path, work: Path) -> tuple[float, list[float], float]:
    """Cut one manifest segment to a 1920x1080 30 fps clip. Returns (seconds, wait-cut label times, raw seconds)."""
    ff = need("ffmpeg")
    src = RAW / seg["file"]
    a = seg["in"]
    b = seg["out"]
    raw_len = (b if b is not None else duration(src)) - a
    removed = [list(c) for c in seg["cut"]]
    labels_src: list[float] = []
    for s, e in seg["idle"]:
        if e - s > IDLE_KEEP + 0.4:
            removed.append([s + IDLE_KEEP, e])
            labels_src.append(s)
    removed = merge([[x - a, y - a] for x, y in removed])
    expr = "1" if not removed else "not(" + "+".join(f"between(t,{x:.3f},{y:.3f})" for x, y in removed) + ")"
    trim = f"trim=start={a:.3f}" + (f":end={b:.3f}" if b is not None else "") + ",setpts=PTS-STARTPTS"
    chain = f"{trim},fps={FPS},select='{expr}',setpts=N/({FPS}*TB)"
    cmd = [ff, "-y", "-i", str(src)]
    if seg["kind"] == "phone":
        bg = work / "phone-bg.png"
        phone_background(bg)
        cmd += ["-loop", "1", "-i", str(bg), "-filter_complex",
                f"[0:v]{chain},scale=468:1013:flags=lanczos[ph];[1:v][ph]overlay=(W-w)/2:(H-h)/2+24:shortest=1,format=yuv420p[v]"]
    else:
        cmd += ["-filter_complex", f"[0:v]{chain},scale=1920:1080:flags=lanczos,format=yuv420p[v]"]
    run(cmd + ["-map", "[v]", *ENC, str(dest)])
    # Where the "Wait cut" tags go, in the clip's own time.
    labels = []
    for s in labels_src:
        rel = s - a
        before = sum(min(y, rel) - x for x, y in removed if x < rel)
        labels.append(round(rel - before, 3))
    return duration(dest), labels, raw_len


def still_clip(png: Path, seconds: float, dest: Path) -> None:
    run([need("ffmpeg"), "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.3f}", "-i", str(png),
         "-vf", "format=yuv420p", *ENC, str(dest)])


def concat(files: list[Path], dest: Path, listfile: Path) -> None:
    listfile.write_text("".join(f"file '{f.resolve()}'\n" for f in files))
    run([need("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(dest)])


def wav_len(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()


def fmt_srt(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main() -> None:
    ensure_dirs()
    ff = need("ffmpeg")
    manifest = json.loads((RAW / "manifest.json").read_text())
    run_info = json.loads((RAW / "run.json").read_text())
    narration, timing, srt = parse_narration(), parse_timing(), parse_srt()
    meta_path = RAW / "tts" / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    work = OUT / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    # Narration length per shot: the real audio if valid, otherwise an estimate at the measured pace.
    real = {s: wav_len(RAW / "tts" / f"{s}.wav") for s in SHOTS
            if (RAW / "tts" / f"{s}.wav").exists() and meta.get(s, {}).get("valid", True)}
    words = {s: len(narration[s].split()) for s in SHOTS}
    wpm = sum(words[s] for s in real) / (sum(real.values()) / 60) if real else 135.0
    narr = {s: real.get(s, words[s] / wpm * 60) for s in SHOTS}
    estimated = [s for s in SHOTS if s not in real]
    if estimated:
        print(f"WARNING: no valid narration audio for {', '.join(estimated)}; using silence of an estimated length ({wpm:.0f} wpm).")

    number = run_info.get("invoice_number", "CM-…")
    shot_files: list[Path] = []
    shot_files_nocap: list[Path] = []
    audio_files: list[Path] = []
    timeline: list[dict] = []
    srt_out: list[str] = []
    cursor = 0.0
    n_cue = 1
    for shot in SHOTS:
        N, win = narr[shot], timing[shot]["window"]
        segs = [m for m in manifest if m["shot"] == shot]
        clips: list[Path] = []
        waits: list[float] = []
        raw_total = 0.0
        L = 0.0
        flags = {k for m in segs for k in ("cached",) if m.get(k)}
        for i, seg in enumerate(segs):
            dest = work / f"{shot}-seg{i}.mp4"
            if seg["kind"] == "placeholder":
                png = work / f"{shot}-ph.png"
                placeholder_card(png, seg["text"], seg["sub"])
                length = max(N + TAIL, 3.0)
                still_clip(png, length, dest)
                dur, lab, raw = length, [], length
            else:
                dur, lab, raw = prepare_footage(seg, dest, work)
            waits += [L + x for x in lab]
            L += dur
            raw_total += raw
            clips.append(dest)

        has_card = shot == "S9"
        notes: list[str] = []
        if has_card:
            T = max(win, N + TAIL, L + 2.0)
            speed = 1.0
        elif L <= win:
            T, speed = max(L, N + TAIL), 1.0
        else:
            speed = min(L / win, MAX_SPEED)
            T = max(L / speed, N + TAIL)
            if L / win > MAX_SPEED:
                notes.append(f"does not fit: footage {L:.1f}s needs {L / win:.2f}x to fit the {win}s window; "
                             f"capped at {MAX_SPEED}x, shot runs {T:.1f}s")
        T = frame_ceil(T)
        if has_card:
            card_png = work / "s9-card.png"
            s9_card(card_png)
            card = work / "S9-card.mp4"
            still_clip(card_png, frame_ceil(T - L) + 0.0, card)
            clips.append(card)
        raw_path = work / f"{shot}-raw.mp4"
        concat(clips, raw_path, work / f"{shot}.txt")
        footage = duration(raw_path)
        pad = max(0.0, T - footage / speed)

        # Overlays.
        extras = []
        if run_info["mode"] == "dry":
            extras.append("DRAFT — dry run on fake runner")
        if "cached" in flags:
            extras.append("Recorded AI result (saved analysis)")
        if shot in estimated:
            extras.append("Narration missing in draft")
        static = work / f"{shot}-static.png"
        static_overlay(static, None, extras)
        layers: list[tuple[Path, float, float]] = [(static, 0, T)]
        texts = [t.format(num=number) for t in SHOT_TEXT[shot]]
        for k, text in enumerate(texts):
            p = work / f"{shot}-lt{k}.png"
            lower_third(p, text)
            layers.append((p, 0.4 + k * T / len(texts) if k else 0.4, (k + 1) * T / len(texts)))
        if speed > 1.02:
            p = work / f"{shot}-speed.png"
            tag(p, f"Sped up {speed:.1f}x")
            layers.append((p, 0, T))
        for k, w in enumerate(waits):
            p = work / f"{shot}-wait.png"
            tag(p, "Wait cut")
            layers.append((p, w / speed, w / speed + IDLE_KEEP / speed))

        # Captions: the script's cues for this shot, spread over the narration by text length.
        start = timing[shot]["start"]
        cues = [c for c in srt if start - 0.01 <= c["start"] < timing[shot]["end"] - 0.01]
        total_chars = sum(len(c["text"]) for c in cues) or 1
        t = 0.0
        caps: list[tuple[Path, float, float]] = []
        for k, c in enumerate(cues):
            span = N * len(c["text"]) / total_chars
            p = work / f"{shot}-cap{k}.png"
            caption(p, c["text"])
            caps.append((p, t, min(t + span, T)))
            srt_out.append(f"{n_cue}\n{fmt_srt(cursor + t)} --> {fmt_srt(cursor + min(t + span, T))}\n{c['text']}\n")
            n_cue += 1
            t += span

        def render(layer_list, dest: Path) -> None:
            cmd = [ff, "-y", "-i", str(raw_path)]
            for p, _, _ in layer_list:
                cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{T:.3f}", "-i", str(p)]
            chain = (f"[0:v]setpts=PTS/{speed:.5f},tpad=stop_mode=clone:stop_duration={pad + 1:.3f},fps={FPS},"
                     f"trim=duration={T:.3f},setpts=PTS-STARTPTS[b0]")
            for i, (_, a, b) in enumerate(layer_list, start=1):
                chain += f";[b{i - 1}][{i}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[b{i}]"
            cmd += ["-filter_complex", chain, "-map", f"[b{len(layer_list)}]", *ENC, "-t", f"{T:.3f}", str(dest)]
            run(cmd)

        v_cap, v_nocap = work / f"{shot}-v.mp4", work / f"{shot}-v-nocap.mp4"
        render(layers + caps, v_cap)
        render(layers, v_nocap)
        shot_files.append(v_cap)
        shot_files_nocap.append(v_nocap)

        a_path = work / f"{shot}-a.wav"
        src = ["-i", str(RAW / "tts" / f"{shot}.wav")] if shot in real else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
        run([ff, "-y", *src, "-af", f"aresample=48000,apad=whole_dur={T:.3f}", "-ac", "1", "-t", f"{T:.3f}",
             "-c:a", "pcm_s16le", str(a_path)])
        audio_files.append(a_path)

        timeline.append({"shot": shot, "start": round(cursor, 2), "duration": round(T, 2),
                         "narration": round(N, 2), "narration_estimated": shot in estimated,
                         "script_window": win, "footage_raw": round(raw_total, 2),
                         "footage_after_trim": round(footage, 2), "speed": round(speed, 2), "notes": notes})
        cursor += T

    # End card: 2 s, silent.
    ec_png = work / "end.png"
    end_card(ec_png)
    ec_v = work / "end-v.mp4"
    still_clip(ec_png, END_CARD, ec_v)
    ec_a = work / "end-a.wav"
    run([ff, "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(END_CARD), "-c:a", "pcm_s16le", str(ec_a)])
    timeline.append({"shot": "END", "start": round(cursor, 2), "duration": END_CARD})
    total = cursor + END_CARD

    audio_all = work / "audio.wav"
    concat(audio_files + [ec_a], audio_all, work / "audio.txt")
    outputs = [(OUT / "creator-milestone-demo.mp4", shot_files, False),
               (OUT / "creator-milestone-demo-softsubs.mp4", shot_files_nocap, True)]
    (OUT / "captions.srt").write_text("\n".join(srt_out), encoding="utf-8")
    for path, files, soft in outputs:
        vid = work / ("video-soft.mp4" if soft else "video.mp4")
        concat(files + [ec_v], vid, work / "video.txt")
        cmd = [ff, "-y", "-i", str(vid), "-i", str(audio_all)]
        if soft:
            cmd += ["-i", str(OUT / "captions.srt")]
        cmd += ["-map", "0:v", "-map", "1:a"] + (["-map", "2:s"] if soft else [])
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
        if soft:
            cmd += ["-c:s", "mov_text", "-metadata:s:s:0", "language=eng"]
        run(cmd + ["-movflags", "+faststart", "-shortest", str(path)])

    (OUT / "timeline.json").write_text(json.dumps({"total": round(total, 2), "mode": run_info["mode"], "shots": timeline}, indent=2))
    print(f"\n{'shot':5}{'narration':>10}{'raw':>8}{'trimmed':>9}{'window':>8}{'speed':>7}{'final':>8}")
    for t in timeline[:-1]:
        est = "*" if t["narration_estimated"] else " "
        print(f"{t['shot']:5}{t['narration']:>9.1f}{est}{t['footage_raw']:>8.1f}{t['footage_after_trim']:>9.1f}"
              f"{t['script_window']:>8}{t['speed']:>7.2f}{t['duration']:>8.1f}  {'; '.join(t['notes'])}")
    print(f"\ntotal {total:.1f}s (limit {LIMIT:.0f}s). * = narration estimated, no valid audio.")
    print(f"wrote {OUT / 'creator-milestone-demo.mp4'}")


if __name__ == "__main__":
    main()
