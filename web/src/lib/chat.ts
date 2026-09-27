import type { DisplayMessage, Notice, ProposedItem, ReceiptProposal } from "../types/chat";
import type { StoredMessage } from "../types/api";
import { isMessageKey } from "./i18n/languages";
import type { MessageKey } from "./i18n/languages";
import { splitReceiptMarker } from "./receipts";

/** Stored history -> display messages. Also returns the indexes of assistant
 * messages whose turn exported a CSV: the file was a client-side blob, never stored,
 * so the caller rebuilds it after a reload instead of leaving "click the file below"
 * pointing at nothing. */
export function mapStoredMessages(items: StoredMessage[]): { messages: DisplayMessage[]; exportIndexes: number[] } {
  const messages: DisplayMessage[] = [];
  const exportIndexes: number[] = [];

  for (const m of items) {
    if (m.role === "user" && m.content?.text) {
      // A receipt upload's stored text carries a "[uploaded receipt: ...]" marker —
      // split it back into text + a viewable image.
      messages.push({ role: "user", seq: m.seq, ...splitReceiptMarker(m.content.text) });
    } else if (m.role === "assistant" && (m.content?.text || m.content?.notice)) {
      if (m.content.tool_calls?.some((c) => c.name === "export_transactions")) exportIndexes.push(messages.length);
      messages.push({ role: "assistant", seq: m.seq, text: m.content.text ?? "", notice: toNotice(m.content.notice) });
    }
  }

  return { messages, exportIndexes };
}

/** A notice from the server, or undefined when there's none — or its key is unknown
 * here (a newer server than this page), rather than showing a raw key. */
export function toNotice(raw: unknown): Notice | undefined {
  const n = raw as { key?: unknown; params?: Record<string, string> } | null | undefined;

  return typeof n?.key === "string" && isMessageKey(n.key) ? { key: n.key, params: n.params ?? {} } : undefined;
}

/** A message's full text as shown: its own text, then its notice in `t`'s language. */
export function messageText(m: DisplayMessage, t: (key: MessageKey, params?: Record<string, string>) => string) {
  const notice = m.notice ? t(m.notice.key, m.notice.params) : "";

  return [m.text, notice].filter(Boolean).join("\n");
}

/** The receipt_proposed SSE payload, with each item's proposed category kept aside
 * so an edit to it can be told apart on confirm. */
export function toReceiptProposal(data: { items: Omit<ProposedItem, "suggested_category">[]; receipt_uri: string }) {
  return {
    items: data.items.map((item) => ({ ...item, suggested_category: item.category })),
    receipt_uri: data.receipt_uri,
  } satisfies ReceiptProposal;
}

/** The API error's `detail` when the message carries a JSON body, else the message. */
export function errorDetail(e: unknown): string {
  const message = e instanceof Error ? e.message : String(e);
  const jsonStart = message.indexOf("{");
  if (jsonStart === -1) return message;

  try {
    return JSON.parse(message.slice(jsonStart)).detail ?? message;
  } catch {
    return message;
  }
}
