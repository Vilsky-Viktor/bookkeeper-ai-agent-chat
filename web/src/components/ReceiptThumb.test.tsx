import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../lib/i18n";
import ReceiptThumb from "./ReceiptThumb";

// userId=null so LanguageProvider skips its preferences fetch and just uses the
// default ("en") — none of these tests touch the network.
function renderThumb(props: Partial<ComponentProps<typeof ReceiptThumb>> = {}) {
  const onView = props.onView ?? vi.fn();
  render(
    <LanguageProvider userId={null}>
      <ReceiptThumb url="https://example.com/receipt.jpg" onView={onView} {...props} />
    </LanguageProvider>,
  );
  return { onView };
}

describe("ReceiptThumb", () => {
  it("renders the image at the given url", () => {
    renderThumb();
    expect(screen.getByAltText("Receipt")).toHaveAttribute("src", "https://example.com/receipt.jpg");
  });

  it("calls onView with the url when clicked", async () => {
    const { onView } = renderThumb();
    await userEvent.click(screen.getByAltText("Receipt"));
    expect(onView).toHaveBeenCalledWith("https://example.com/receipt.jpg");
  });

  it("calls onLoad once the image finishes loading", () => {
    const onLoad = vi.fn();
    renderThumb({ onLoad });
    fireEvent.load(screen.getByAltText("Receipt"));
    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  it("falls back to a plain link when the image fails to load (e.g. a PDF receipt)", () => {
    renderThumb();
    fireEvent.error(screen.getByAltText("Receipt"));

    expect(screen.queryByAltText("Receipt")).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: "View attachment" });
    expect(link).toHaveAttribute("href", "https://example.com/receipt.jpg");
    expect(link).toHaveAttribute("target", "_blank");
  });
});
