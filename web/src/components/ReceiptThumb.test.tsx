import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../lib/i18n";
import { renderPdfFirstPageToDataUrl } from "../lib/pdfThumbnail";
import ReceiptThumb from "./ReceiptThumb";

vi.mock("../lib/pdfThumbnail", () => ({ renderPdfFirstPageToDataUrl: vi.fn() }));

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

  it("renders a PDF's first page as the thumbnail when the image fails to load", async () => {
    vi.mocked(renderPdfFirstPageToDataUrl).mockResolvedValue("data:image/png;base64,fake-thumbnail");
    renderThumb();

    fireEvent.error(screen.getByAltText("Receipt"));

    expect(renderPdfFirstPageToDataUrl).toHaveBeenCalledWith("https://example.com/receipt.jpg");
    await screen.findByRole("img", { name: "Receipt" }); // waits out the pending promise
    expect(screen.getByAltText("Receipt")).toHaveAttribute("src", "data:image/png;base64,fake-thumbnail");
  });

  it("falls back to a plain link when it's not an image and PDF rendering also fails", async () => {
    vi.mocked(renderPdfFirstPageToDataUrl).mockRejectedValue(new Error("not a PDF either"));
    renderThumb();

    fireEvent.error(screen.getByAltText("Receipt"));

    const link = await screen.findByRole("link", { name: "View attachment" });
    expect(link).toHaveAttribute("href", "https://example.com/receipt.jpg");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("falls back to a plain link if the rendered PDF thumbnail itself fails to display", async () => {
    vi.mocked(renderPdfFirstPageToDataUrl).mockResolvedValue("data:image/png;base64,fake-thumbnail");
    renderThumb();
    fireEvent.error(screen.getByAltText("Receipt"));
    await screen.findByRole("img", { name: "Receipt" });

    fireEvent.error(screen.getByAltText("Receipt")); // the rendered thumbnail <img> itself errors

    const link = await screen.findByRole("link", { name: "View attachment" });
    expect(link).toHaveAttribute("href", "https://example.com/receipt.jpg");
  });
});
