import type { TransactionFilter } from "./api";

// The table's resting state — current calendar month — used both on first load and
// whenever the chat clears the filter (an empty filter_set event means "back to
// default", not "show everything").
export function defaultFilter(): TransactionFilter {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth(); // 0-indexed
  const pad = (n: number) => String(n).padStart(2, "0");
  const lastDay = new Date(year, month + 1, 0).getDate();
  return {
    from: `${year}-${pad(month + 1)}-01`,
    to: `${year}-${pad(month + 1)}-${pad(lastDay)}`,
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
