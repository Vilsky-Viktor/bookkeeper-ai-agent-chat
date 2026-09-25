import { describe, expect, it } from "vitest";
import { receiptViewUrl, receiptViewUrlFromObject, splitReceiptMarker } from "./receipts";

describe("receiptViewUrl", () => {
  it("builds a same-origin download URL from a gs:// receipt_uri", () => {
    expect(receiptViewUrl("gs://mybucket/receipts/u1/x.jpg")).toBe(
      "/gcs/download/storage/v1/b/mybucket/o/receipts%2Fu1%2Fx.jpg?alt=media",
    );
  });

  it("returns null for null/undefined/empty input", () => {
    expect(receiptViewUrl(null)).toBeNull();
    expect(receiptViewUrl(undefined)).toBeNull();
    expect(receiptViewUrl("")).toBeNull();
  });

  it("returns null for a uri that isn't gs://", () => {
    expect(receiptViewUrl("https://example.com/receipt.jpg")).toBeNull();
  });
});

describe("receiptViewUrlFromObject", () => {
  it("builds a URL against the configured bucket from a bare object path", () => {
    // No VITE_RECEIPTS_BUCKET is set in the test env, so this exercises the
    // "receipts-local" fallback — the same default services/agent's storage.py uses.
    expect(receiptViewUrlFromObject("receipts/u1/x.jpg")).toBe(
      "/gcs/download/storage/v1/b/receipts-local/o/receipts%2Fu1%2Fx.jpg?alt=media",
    );
  });

  it("returns null for null/undefined/empty input", () => {
    expect(receiptViewUrlFromObject(null)).toBeNull();
    expect(receiptViewUrlFromObject(undefined)).toBeNull();
    expect(receiptViewUrlFromObject("")).toBeNull();
  });
});

describe("splitReceiptMarker", () => {
  it("returns the text unchanged when there's no marker", () => {
    expect(splitReceiptMarker("just a normal message")).toEqual({ text: "just a normal message" });
  });

  it("splits the marker off and resolves it to a viewable image URL", () => {
    const result = splitReceiptMarker("Please extract this receipt.\n\n[uploaded receipt: receipts/u1/x.jpg]");
    expect(result.text).toBe("Please extract this receipt.");
    expect(result.imageUrl).toBe("/gcs/download/storage/v1/b/receipts-local/o/receipts%2Fu1%2Fx.jpg?alt=media");
  });

  it("only matches the marker at the very end of the text", () => {
    const text = "[uploaded receipt: receipts/u1/x.jpg] mentioned mid-sentence, not a real marker";
    expect(splitReceiptMarker(text)).toEqual({ text });
  });
});
