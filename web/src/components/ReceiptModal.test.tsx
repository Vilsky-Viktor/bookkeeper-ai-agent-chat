import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../lib/i18n";
import ReceiptModal from "./ReceiptModal";

function wrapper({ children }: { children: ReactNode }) {
  return <LanguageProvider userId={null}>{children}</LanguageProvider>;
}

describe("ReceiptModal", () => {
  it("renders nothing when url is null", () => {
    const { container } = render(<ReceiptModal url={null} onClose={vi.fn()} />, { wrapper });
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the receipt image when url is set", () => {
    render(<ReceiptModal url="https://example.com/receipt.jpg" onClose={vi.fn()} />, { wrapper });
    expect(screen.getByAltText("Receipt")).toHaveAttribute("src", "https://example.com/receipt.jpg");
  });

  it("calls onClose when the backdrop is clicked", () => {
    const onClose = vi.fn();
    const { container } = render(<ReceiptModal url="https://example.com/receipt.jpg" onClose={onClose} />, {
      wrapper,
    });
    fireEvent.click(container.firstChild as Element);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when the image itself is clicked", () => {
    const onClose = vi.fn();
    render(<ReceiptModal url="https://example.com/receipt.jpg" onClose={onClose} />, { wrapper });
    fireEvent.click(screen.getByAltText("Receipt"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<ReceiptModal url="https://example.com/receipt.jpg" onClose={onClose} />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose on Escape", () => {
    const onClose = vi.fn();
    render(<ReceiptModal url="https://example.com/receipt.jpg" onClose={onClose} />, { wrapper });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not respond to Escape once closed (url null)", () => {
    const onClose = vi.fn();
    render(<ReceiptModal url={null} onClose={onClose} />, { wrapper });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("falls back to an external link when the image fails to load (e.g. a PDF)", () => {
    render(<ReceiptModal url="https://example.com/receipt.pdf" onClose={vi.fn()} />, { wrapper });
    fireEvent.error(screen.getByAltText("Receipt"));

    expect(screen.queryByAltText("Receipt")).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open in a new tab" });
    expect(link).toHaveAttribute("href", "https://example.com/receipt.pdf");
  });

  it("resets the failed state when a new url is passed in", () => {
    const { rerender } = render(<ReceiptModal url="https://example.com/a.pdf" onClose={vi.fn()} />, { wrapper });
    fireEvent.error(screen.getByAltText("Receipt"));
    expect(screen.queryByAltText("Receipt")).not.toBeInTheDocument();

    rerender(
      <LanguageProvider userId={null}>
        <ReceiptModal url="https://example.com/b.jpg" onClose={vi.fn()} />
      </LanguageProvider>,
    );

    expect(screen.getByAltText("Receipt")).toHaveAttribute("src", "https://example.com/b.jpg");
  });
});
