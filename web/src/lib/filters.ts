import type { TransactionFilter } from "./api";

// The table's resting state — a rolling last-30-days window — used both on first load
// and whenever the chat clears the filter (an empty filter_set event means "back to
// default", not "show everything"). A rolling window instead of the current calendar
// month avoids showing an empty table for everyone in the first few days of a new
// month, before this month has any transactions yet.
export function defaultFilter(): TransactionFilter {
  const format = (d: Date) => {
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 29); // 29 days back + today = a 30-day window
  return {
    from: format(from),
    to: format(to),
  };
}

// transactions-<current date/time>.csv — a plain timestamp, not filter-derived, so
// exporting the same filter twice doesn't produce a name that looks like a duplicate
// (or, worse, collides and gets confused with an earlier download).
export function exportFilename(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp =
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
  return `transactions-${stamp}.csv`;
}
