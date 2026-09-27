// Grouping-only: the API returns an exact decimal string (integer minor units under
// the hood, see services/transactions/app/helpers/money.py) — this never parses it as a
// number, so there's no float rounding risk, just thousands separators inserted into
// the integer part.
export function formatAmount(amount: string): string {
  const [intPart, decPart] = amount.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

  return decPart !== undefined ? `${grouped}.${decPart}` : grouped;
}
