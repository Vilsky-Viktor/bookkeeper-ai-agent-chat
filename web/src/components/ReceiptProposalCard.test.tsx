import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ReceiptProposal } from "../lib/chat";
import { LanguageProvider } from "../lib/i18n";
import ReceiptProposalCard from "./ReceiptProposalCard";

function wrapper({ children }: { children: ReactNode }) {
  return <LanguageProvider userId={null}>{children}</LanguageProvider>;
}

const proposal: ReceiptProposal = {
  receipt_uri: "gs://b/r",
  items: [
    {
      occurred_on: "2026-01-01",
      type: "expense",
      amount: "84700",
      currency: "IDR",
      category: "dining",
      suggested_category: "dining",
      description: "Food delivery order - Warung",
      receipt_uri: "gs://b/r",
    },
  ],
};

function renderCard() {
  const handlers = { onChange: vi.fn(), onConfirm: vi.fn(), onCancel: vi.fn() };
  render(<ReceiptProposalCard proposal={proposal} {...handlers} />, { wrapper });
  return handlers;
}

describe("ReceiptProposalCard", () => {
  it("shows the proposed fields as editable inputs", () => {
    renderCard();
    expect(screen.getByDisplayValue("Food delivery order - Warung")).toBeInTheDocument();
    expect(screen.getByDisplayValue("84700")).toBeInTheDocument();
    expect(screen.getByDisplayValue("IDR")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Dining")).toBeInTheDocument();
  });

  it("reports edits by item index and field, uppercasing the currency", () => {
    const { onChange } = renderCard();
    fireEvent.change(screen.getByDisplayValue("Dining"), { target: { value: "shopping" } });
    fireEvent.change(screen.getByDisplayValue("IDR"), { target: { value: "usd" } });
    expect(onChange).toHaveBeenCalledWith(0, "category", "shopping");
    expect(onChange).toHaveBeenCalledWith(0, "currency", "USD");
  });

  it("confirms and cancels", () => {
    const { onConfirm, onCancel } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Confirm & save" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("has no per-row delete or add-item controls (a receipt is one transaction)", () => {
    renderCard();
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });
});
