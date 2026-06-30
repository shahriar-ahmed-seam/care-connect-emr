export const BDT_SYMBOL = "৳";

export function formatBDT(amount: number | string): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(value)) {
    return `${BDT_SYMBOL}0.00`;
  }
  const fixed = Math.abs(value).toFixed(2);
  const [whole, fraction] = fixed.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const sign = value < 0 ? "-" : "";
  return `${sign}${BDT_SYMBOL}${grouped}.${fraction}`;
}

/** Pad a number to two digits. */
function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/**
 * Format a date as DD/MM/YYYY. Accepts a Date or an ISO/date string.
 */
export function formatDate(input: Date | string): string {
  const date = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return `${pad2(date.getDate())}/${pad2(date.getMonth() + 1)}/${date.getFullYear()}`;
}

/** Format the time portion of a datetime as HH:MM (24-hour). */
export function formatTime(input: Date | string): string {
  const date = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}
