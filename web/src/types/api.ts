// Shapes of the backend APIs' requests and responses.

export type ReceiptContentType = "image/jpeg" | "application/pdf";

export interface Transaction {
  id: string;
  uid: string;
  occurred_on: string;
  type: "expense" | "income";
  amount: string;
  currency: string;
  category: string;
  description: string | null;
  receipt_uri: string | null;
  batch_id: string | null;
  created_at: string;
}

export interface TransactionFilter {
  currency?: string;
  category?: string;
  type?: string;
  from?: string;
  to?: string;
  min_amount?: string;
  max_amount?: string;
  description?: string;
}

export interface ThreadSummary {
  id: string;
  title: string | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface StoredMessageContent {
  text?: string;
  tool_calls?: { name?: string }[];
  notice?: { key: string; params?: Record<string, string> } | null;
  [key: string]: unknown;
}

export interface StoredMessage {
  seq: number;
  role: "user" | "assistant" | "tool";
  content: StoredMessageContent;
  created_at: string;
}

export interface UploadTarget {
  method: string;
  object: string;
  url: string;
}

export interface Preferences {
  language: string;
  default_currency: string | null;
}
