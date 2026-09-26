import type { Transaction } from "./api";

function csvField(value: string | number | null | undefined): string {
  const s = value == null ? "" : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const HEADERS = ["Date", "Type", "Amount", "Currency", "Category", "Description"];

export function transactionsToCsv(items: Transaction[]): string {
  const rows = items.map((t) => [
    t.occurred_on,
    t.type,
    t.type === "expense" ? `-${t.amount}` : t.amount, // signed, so a spreadsheet SUM() nets correctly
    t.currency,
    t.category,
    t.description ?? "",
  ]);
  return [HEADERS, ...rows].map((row) => row.map(csvField).join(",")).join("\r\n");
}

// Object URLs stay valid for the page's lifetime once created (until explicitly
// revoked) — that's exactly what's wanted here: the file is built once, when the
// export happens, and the resulting link stays clickable for the rest of the session.
export function createCsvObjectUrl(items: Transaction[]): string {
  const blob = new Blob([transactionsToCsv(items)], { type: "text/csv;charset=utf-8;" });
  return URL.createObjectURL(blob);
}

// A cheap, decorative grid for FileAttachment's thumbnail — not a real CSV parser
// (a naive comma split misreads a quoted field's own embedded comma), which is fine
// here since this only ever feeds a tiny visual preview, never the real export data.
export function parseCsvPreviewRows(text: string, maxRows: number, maxCols: number): string[][] {
  return text
    .split(/\r\n|\n/)
    .filter((line) => line.length > 0)
    .slice(0, maxRows)
    .map((line) =>
      line
        .split(",")
        .slice(0, maxCols)
        .map((cell) => cell.replaceAll('"', "")),
    );
}
