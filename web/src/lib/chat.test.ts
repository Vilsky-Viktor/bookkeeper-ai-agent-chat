import { describe, expect, it } from "vitest";
import type { StoredMessage } from "./api";
import { errorDetail, mapStoredMessages, toReceiptProposal } from "./chat";

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
