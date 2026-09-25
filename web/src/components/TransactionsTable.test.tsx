import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Transaction, TransactionFilter } from "../lib/api";
import { LanguageProvider } from "../lib/i18n";
import TransactionsTable from "./TransactionsTable";

const { listTransactionsMock } = vi.hoisted(() => ({ listTransactionsMock: vi.fn() }));
vi.mock("../lib/api", () => ({ listTransactions: listTransactionsMock }));

function tx(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: "t1",
    uid: "u1",
    occurred_on: "2026-01-15",
    type: "expense",
    amount: "1234.50",
    currency: "USD",
    category: "dining",
    description: "coffee",
    receipt_uri: null,
    batch_id: null,
    created_at: "2026-01-15T10:00:00Z",
    ...overrides,
  };
}

function renderTable(props?: {
  filter?: TransactionFilter;
  onViewImage?: (url: string) => void;
  onReferenceTransaction?: (id: string) => void;
}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onViewImage = props?.onViewImage ?? vi.fn();
  const onReferenceTransaction = props?.onReferenceTransaction ?? vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <LanguageProvider userId={null}>
        <TransactionsTable
          filter={props?.filter ?? {}}
          onViewImage={onViewImage}
          onReferenceTransaction={onReferenceTransaction}
        />
      </LanguageProvider>
    </QueryClientProvider>,
  );
  return { onViewImage, onReferenceTransaction };
}

describe("TransactionsTable", () => {
  beforeEach(() => {
    listTransactionsMock.mockReset();
  });

  it("shows the empty state once loaded with no rows", async () => {
    listTransactionsMock.mockResolvedValue({ items: [], next_cursor: null });
    renderTable();
    expect(await screen.findByText("No transactions found. Start by chatting.")).toBeInTheDocument();
  });

  it("renders a fetched row: formatted date, signed+grouped amount, translated category", async () => {
    listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
    renderTable();
    const description = await screen.findByText("coffee");
    const row = description.closest("tr")!;
    expect(row).toHaveTextContent("-1,234.50");
    expect(screen.getByText("15.01.2026")).toBeInTheDocument();
    expect(screen.getByText("Dining")).toBeInTheDocument(); // tCategory("dining")
  });

  it("shows income unsigned", async () => {
    listTransactionsMock.mockResolvedValue({
      items: [tx({ type: "income", amount: "500.00", description: "salary" })],
      next_cursor: null,
    });
    renderTable();
    const description = await screen.findByText("salary");
    const row = description.closest("tr")!;
    expect(row).toHaveTextContent("500.00");
    expect(row).not.toHaveTextContent("-500.00");
  });

  it("shows a receipt button only when the row has a receipt, and it resolves to a viewable url", async () => {
    listTransactionsMock.mockResolvedValue({
      items: [tx({ id: "with-receipt", receipt_uri: "gs://receipts-local/receipts/u1/x.jpg" })],
      next_cursor: null,
    });
    const { onViewImage } = renderTable();
    const button = await screen.findByRole("button", { name: "View receipt" });
    button.click();
    expect(onViewImage).toHaveBeenCalledWith(
      "/gcs/download/storage/v1/b/receipts-local/o/receipts%2Fu1%2Fx.jpg?alt=media",
    );
  });

  it("omits the receipt button when the row has no receipt", async () => {
    listTransactionsMock.mockResolvedValue({ items: [tx({ receipt_uri: null })], next_cursor: null });
    renderTable();
    await screen.findByText("coffee");
    expect(screen.queryByRole("button", { name: "View receipt" })).not.toBeInTheDocument();
  });

  it("calls onReferenceTransaction with the row's id", async () => {
    listTransactionsMock.mockResolvedValue({ items: [tx({ id: "txn-42" })], next_cursor: null });
    const { onReferenceTransaction } = renderTable();
    const button = await screen.findByRole("button", { name: "Reference in chat" });
    button.click();
    expect(onReferenceTransaction).toHaveBeenCalledWith("txn-42");
  });

  it("passes the filter through to listTransactions", async () => {
    listTransactionsMock.mockResolvedValue({ items: [], next_cursor: null });
    renderTable({ filter: { category: "dining" } });
    await waitFor(() => expect(listTransactionsMock).toHaveBeenCalledWith({ category: "dining" }, undefined));
  });
});
