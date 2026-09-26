import { describe, expect, it, vi } from "vitest";
import type { Transaction } from "./api";
import { createCsvObjectUrl, parseCsvPreviewRows, transactionsToCsv } from "./csv";

function tx(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: "t1",
    uid: "u1",
    occurred_on: "2026-01-15",
    type: "expense",
    amount: "12.50",
    currency: "USD",
    category: "dining",
    description: "coffee",
    receipt_uri: null,
    batch_id: null,
    created_at: "2026-01-15T10:00:00Z",
    ...overrides,
  };
}

describe("transactionsToCsv", () => {
  it("starts with the header row", () => {
    const csv = transactionsToCsv([]);
    expect(csv).toBe("Date,Type,Amount,Currency,Category,Description");
  });

  it("signs an expense negative so a spreadsheet SUM() nets correctly", () => {
    const csv = transactionsToCsv([tx({ type: "expense", amount: "12.50" })]);
    expect(csv).toContain(",-12.50,");
  });

  it("leaves income unsigned", () => {
    const csv = transactionsToCsv([tx({ type: "income", amount: "500.00" })]);
    expect(csv).toContain(",500.00,");
  });

  it("renders a null description as an empty field", () => {
    const csv = transactionsToCsv([tx({ description: null })]);
    const [, dataRow] = csv.split("\r\n");
    expect(dataRow.endsWith(",")).toBe(true);
  });

  it("quotes and escapes a field containing a comma", () => {
    const csv = transactionsToCsv([tx({ description: "coffee, milk" })]);
    expect(csv).toContain('"coffee, milk"');
  });

  it("quotes and escapes a field containing a double quote", () => {
    const csv = transactionsToCsv([tx({ description: 'the "usual" order' })]);
    expect(csv).toContain('"the ""usual"" order"');
  });

  it("quotes a field containing a newline", () => {
    const csv = transactionsToCsv([tx({ description: "line one\nline two" })]);
    expect(csv).toContain('"line one\nline two"');
  });

  it("joins multiple rows with CRLF", () => {
    const csv = transactionsToCsv([tx({ id: "t1" }), tx({ id: "t2" })]);
    expect(csv.split("\r\n")).toHaveLength(3); // header + 2 rows
  });
});

describe("createCsvObjectUrl", () => {
  it("builds a text/csv blob and hands it to URL.createObjectURL", async () => {
    const createObjectURL = vi.fn((_obj: Blob | MediaSource) => "blob:mock-url");
    vi.stubGlobal("URL", { ...URL, createObjectURL });

    const result = createCsvObjectUrl([tx()]);

    expect(result).toBe("blob:mock-url");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(blob.type).toBe("text/csv;charset=utf-8;");
    expect(await blob.text()).toBe(transactionsToCsv([tx()]));

    vi.unstubAllGlobals();
  });
});

describe("parseCsvPreviewRows", () => {
  it("splits lines into cells", () => {
    const csv = transactionsToCsv([tx()]);
    expect(parseCsvPreviewRows(csv, 6, 4)).toEqual([
      ["Date", "Type", "Amount", "Currency"],
      ["2026-01-15", "expense", "-12.50", "USD"],
    ]);
  });

  it("caps the number of rows", () => {
    const csv = transactionsToCsv([tx({ id: "t1" }), tx({ id: "t2" }), tx({ id: "t3" })]);
    expect(parseCsvPreviewRows(csv, 2, 6)).toHaveLength(2); // header + 1 data row
  });

  it("caps the number of columns", () => {
    const csv = transactionsToCsv([tx()]);
    expect(parseCsvPreviewRows(csv, 6, 2)[0]).toEqual(["Date", "Type"]);
  });

  it("strips quote characters from a quoted field", () => {
    const csv = transactionsToCsv([tx({ description: "coffee, milk" })]);
    const rows = parseCsvPreviewRows(csv, 6, 6);
    expect(rows[1].at(-1)).not.toContain('"');
  });

  it("skips blank lines", () => {
    expect(parseCsvPreviewRows("a,b\n\nc,d", 6, 6)).toEqual([
      ["a", "b"],
      ["c", "d"],
    ]);
  });

  it("returns an empty array for empty input", () => {
    expect(parseCsvPreviewRows("", 6, 6)).toEqual([]);
  });
});
