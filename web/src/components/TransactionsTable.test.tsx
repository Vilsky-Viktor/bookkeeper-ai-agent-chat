import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Transaction, TransactionFilter } from "../lib/api";
import { LanguageProvider } from "../lib/i18n";
import TransactionsTable from "./TransactionsTable";

const { listTransactionsMock, patchTransactionMock, deleteTransactionMock } = vi.hoisted(() => ({
  listTransactionsMock: vi.fn(),
  patchTransactionMock: vi.fn(),
  deleteTransactionMock: vi.fn(),
}));
vi.mock("../lib/api", () => ({
  listTransactions: listTransactionsMock,
  patchTransaction: patchTransactionMock,
  deleteTransaction: deleteTransactionMock,
}));

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
    patchTransactionMock.mockReset().mockResolvedValue({});
    deleteTransactionMock.mockReset().mockResolvedValue({ deleted: "t1" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the empty state once loaded with no rows", async () => {
    listTransactionsMock.mockResolvedValue({ items: [], next_cursor: null });
    renderTable();
    expect(await screen.findByText("No transactions found. Start by chatting.")).toBeInTheDocument();
  });

  it("renders a fetched row's fields as editable inputs", async () => {
    listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
    renderTable();
    await screen.findByDisplayValue("coffee");
    expect(screen.getByDisplayValue("2026-01-15")).toBeInTheDocument();
    expect(screen.getByDisplayValue("1,234.50")).toBeInTheDocument(); // grouped, per formatAmount
    expect(screen.getByDisplayValue("USD")).toBeInTheDocument();
    expect(screen.getByText("Dining")).toBeInTheDocument(); // tCategory("dining") <option>
  });

  it("shows a minus sign for an expense and none for income", async () => {
    listTransactionsMock.mockResolvedValue({
      items: [tx({ id: "t1", type: "expense" }), tx({ id: "t2", type: "income", description: "salary" })],
      next_cursor: null,
    });
    renderTable();
    const expenseRow = (await screen.findByDisplayValue("coffee")).closest("tr")!;
    const incomeRow = screen.getByDisplayValue("salary").closest("tr")!;
    expect(within(expenseRow).getByText("-")).toBeInTheDocument();
    expect(within(incomeRow).queryByText("-")).not.toBeInTheDocument();
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
    await screen.findByDisplayValue("coffee");
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

  describe("editing", () => {
    it("patches the description on blur when it changed", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      const input = await screen.findByDisplayValue("coffee");
      fireEvent.change(input, { target: { value: "tea" } });
      fireEvent.blur(input);
      await waitFor(() =>
        expect(patchTransactionMock).toHaveBeenCalledWith("t1", { description: "tea" }, expect.any(String)),
      );
    });

    it("does not call patch on blur when the value is unchanged", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      const input = await screen.findByDisplayValue("coffee");
      fireEvent.blur(input);
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(patchTransactionMock).not.toHaveBeenCalled();
    });

    it("strips thousands-separator commas before patching the amount", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      const input = await screen.findByDisplayValue("1,234.50");
      fireEvent.change(input, { target: { value: "2,000.00" } });
      fireEvent.blur(input);
      await waitFor(() =>
        expect(patchTransactionMock).toHaveBeenCalledWith("t1", { amount: "2000.00" }, expect.any(String)),
      );
    });

    it("uppercases the currency before patching", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      const input = await screen.findByDisplayValue("USD");
      fireEvent.change(input, { target: { value: "eur" } });
      fireEvent.blur(input);
      await waitFor(() =>
        expect(patchTransactionMock).toHaveBeenCalledWith("t1", { currency: "EUR" }, expect.any(String)),
      );
    });

    it("patches the category immediately when the dropdown changes", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      await screen.findByDisplayValue("coffee");
      const select = screen.getByDisplayValue("Dining");
      fireEvent.change(select, { target: { value: "groceries" } });
      await waitFor(() =>
        expect(patchTransactionMock).toHaveBeenCalledWith("t1", { category: "groceries" }, expect.any(String)),
      );
    });

    it("keeps a custom (non-built-in) category as a selectable option instead of dropping it", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx({ category: "side hustle" })], next_cursor: null });
      renderTable();
      await screen.findByDisplayValue("coffee");
      expect(screen.getByText("side hustle")).toBeInTheDocument();
    });

    it("patches the date immediately when it changes", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      const dateInput = await screen.findByDisplayValue("2026-01-15");
      fireEvent.change(dateInput, { target: { value: "2026-02-01" } });
      await waitFor(() =>
        expect(patchTransactionMock).toHaveBeenCalledWith("t1", { occurred_on: "2026-02-01" }, expect.any(String)),
      );
    });
  });

  describe("deleting", () => {
    it("shows a confirmation dialog instead of deleting immediately", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      const button = await screen.findByRole("button", { name: "Delete transaction" });
      button.click();

      expect(await screen.findByText("Delete this transaction? This can't be undone.")).toBeInTheDocument();
      expect(deleteTransactionMock).not.toHaveBeenCalled();
    });

    it("deletes after the user confirms in the dialog", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      (await screen.findByRole("button", { name: "Delete transaction" })).click();

      (await screen.findByRole("button", { name: "Delete" })).click();

      await waitFor(() => expect(deleteTransactionMock).toHaveBeenCalledWith("t1", expect.any(String)));
    });

    it("does not delete and closes the dialog when the user cancels", async () => {
      listTransactionsMock.mockResolvedValue({ items: [tx()], next_cursor: null });
      renderTable();
      (await screen.findByRole("button", { name: "Delete transaction" })).click();

      (await screen.findByRole("button", { name: "Cancel" })).click();

      await waitFor(() =>
        expect(screen.queryByText("Delete this transaction? This can't be undone.")).not.toBeInTheDocument(),
      );
      expect(deleteTransactionMock).not.toHaveBeenCalled();
    });
  });
});
