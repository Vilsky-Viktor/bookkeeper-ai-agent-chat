import type { MessageKey } from "../lib/i18n/languages";

/** A fixed reply the server sends as a key (see services/agent/app/models/notices.py),
 * shown in the user's current language. */
export interface Notice {
  key: MessageKey;
  params?: Record<string, string>;
}

export interface DisplayMessage {
  role: "user" | "assistant";
  text: string;
  notice?: Notice;
  imageUrl?: string;
  csvUrl?: string;
  csvFilename?: string;
  // Only set for messages loaded from history (not ones just sent locally) — used to
  // paginate further back via before_seq.
  seq?: number;
}

export interface ProposedItem {
  occurred_on: string;
  type: string;
  amount: string;
  currency: string;
  category: string;
  // The category the app proposed. Sent back on confirm so the server learns a
  // correction only when the user actually changed it.
  suggested_category: string;
  description: string | null;
  receipt_uri: string;
}

export interface ReceiptProposal {
  items: ProposedItem[];
  receipt_uri: string;
}
