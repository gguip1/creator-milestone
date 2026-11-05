// The only place money and dates are formatted. Money stays in integer minor units; no float math.

const EXPONENTS: Record<string, number> = { USD: 2 };

function exponent(currency: string): number {
  return EXPONENTS[currency] ?? 2;
}

/** 9000 -> "$90.00". Splits the integer instead of dividing, so there is no rounding error. */
export function formatMoney(minor: number | null | undefined, currency = "USD"): string {
  if (minor === null || minor === undefined) return "—";
  const digits = exponent(currency);
  const base = 10 ** digits;
  const abs = Math.abs(minor);
  const whole = Math.trunc(abs / base).toLocaleString("en-US");
  const fraction = String(abs % base).padStart(digits, "0");
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${minor < 0 ? "-" : ""}${symbol}${whole}.${fraction}`;
}

/** "300.00" or "300" -> 30000. Returns null when the text is not a plain amount. */
export function parseMoney(text: string, currency = "USD"): number | null {
  const digits = exponent(currency);
  const match = /^\s*\$?\s*(\d{1,9})(?:\.(\d{1,2}))?\s*$/.exec(text.replace(/,/g, ""));
  if (!match) return null;
  const fraction = (match[2] ?? "").padEnd(digits, "0");
  return Number(match[1]) * 10 ** digits + Number(fraction);
}

/** Plain decimal for an input field: 30000 -> "300.00". */
export function moneyInput(minor: number | null | undefined, currency = "USD"): string {
  return minor === null || minor === undefined ? "" : formatMoney(minor, currency).replace(/^[^\d-]*/, "");
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function percent(basisPoints: number | null): string {
  if (basisPoints === null) return "";
  return `${basisPoints / 100}%`;
}
