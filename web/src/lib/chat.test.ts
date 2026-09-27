import { describe, expect, it } from "vitest";
import type { StoredMessage } from "./api";
import { errorDetail, mapStoredMessages, messageText, toReceiptProposal } from "./chat";
import { LOCALES } from "./i18n/languages";

function stored(seq: number, role: StoredMessage["role"], content: StoredMessage["content"]): StoredMessage {
  return { seq, role, content, created_at: "2026-01-01T00:00:00Z" };
}

describe("mapStoredMessages", () => {
  it("keeps user and assistant text, skips tool rows, and splits a receipt marker into an image", () => {
    const { messages } = mapStoredMessages([
      stored(1, "user", { text: "lunch\n\n[uploaded receipt: receipts/u1/r.jpg]" }),
      stored(2, "tool", { name: "extract_receipt" }),
      stored(3, "assistant", { text: "Extracted it." }),
    ]);

    expect(messages.map((m) => [m.role, m.text, m.seq])).toEqual([
      ["user", "lunch", 1],
      ["assistant", "Extracted it.", 3],
    ]);
    expect(messages[0].imageUrl).toContain("receipts%2Fu1%2Fr.jpg");
  });

  it("reports which assistant messages came from an export turn", () => {
    const { exportIndexes } = mapStoredMessages([
      stored(1, "user", { text: "export" }),
      stored(2, "assistant", { text: "Here it is.", tool_calls: [{ name: "export_transactions" }] }),
      stored(3, "user", { text: "thanks" }),
      stored(4, "assistant", { text: "Anytime." }),
    ]);
    expect(exportIndexes).toEqual([1]);
  });

  it("keeps a stored notice, so it's shown in the current language", () => {
    const { messages } = mapStoredMessages([
      stored(1, "assistant", { text: "", notice: { key: "receiptProposed", params: { date: "2026-09-26" } } }),
      stored(2, "assistant", { text: "", notice: { key: "noSuchKey" } }),
    ]);
    expect(messages.map((m) => m.notice)).toEqual([
      { key: "receiptProposed", params: { date: "2026-09-26" } },
      undefined, // a key this page doesn't know isn't shown raw
    ]);
  });
});

describe("messageText", () => {
  const tIn =
    (lang: keyof typeof LOCALES) => (key: keyof (typeof LOCALES)["en"]["ui"], params?: Record<string, string>) =>
      LOCALES[lang].ui[key].replace(/\{(\w+)\}/g, (m, name: string) => params?.[name] ?? m);

  it("shows the text, then the notice worded in the given language", () => {
    const m = { role: "assistant" as const, text: "Partial", notice: { key: "turnFailed" as const } };
    expect(messageText(m, tIn("en"))).toBe(`Partial\n${LOCALES.en.ui.turnFailed}`);
    expect(messageText(m, tIn("uk"))).toBe(`Partial\n${LOCALES.uk.ui.turnFailed}`);
  });

  it("fills a notice's params", () => {
    const m = {
      role: "assistant" as const,
      text: "",
      notice: { key: "receiptProposed" as const, params: { date: "2026-09-26" } },
    };
    expect(messageText(m, tIn("en"))).toContain("2026-09-26");
  });
});

describe("toReceiptProposal", () => {
  it("remembers each item's proposed category so an edit can be detected on confirm", () => {
    const proposal = toReceiptProposal({
      items: [
        {
          occurred_on: "2026-01-01",
          type: "expense",
          amount: "10",
          currency: "USD",
          category: "dining",
          description: "Lunch",
          receipt_uri: "gs://b/r",
        },
      ],
      receipt_uri: "gs://b/r",
    });
    expect(proposal.items[0].suggested_category).toBe("dining");
  });
});

describe("errorDetail", () => {
  it("extracts the API's detail from an error carrying a JSON body", () => {
    expect(errorDetail(new Error('create transactions failed: 400 {"detail":"bad amount"}'))).toBe("bad amount");
  });

  it("falls back to the message when there's no JSON, or it doesn't parse", () => {
    expect(errorDetail(new Error("network down"))).toBe("network down");
    expect(errorDetail(new Error("oops {not json"))).toBe("oops {not json");
  });
});
