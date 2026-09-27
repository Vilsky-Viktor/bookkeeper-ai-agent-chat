import type {
  Preferences,
  ReceiptContentType,
  StoredMessage,
  ThreadSummary,
  Transaction,
  TransactionFilter,
  UploadTarget,
} from "../types/api";
import { auth } from "./firebase";

export async function authHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  const user = auth.currentUser;
  const token = user ? await user.getIdToken() : "";

  return {
    Authorization: `Bearer ${token}`,
    ...extra,
  };
}

async function unwrap<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${what} failed: ${res.status} ${body}`);
  }

  return res.json() as Promise<T>;
}

export async function listTransactions(
  filter: TransactionFilter,
  cursor?: string,
): Promise<{ items: Transaction[]; next_cursor: string | null }> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filter)) if (v) params.set(k, v);
  if (cursor) params.set("cursor", cursor);
  const res = await fetch(`/api/transactions/transactions?${params}`, { headers: await authHeaders() });

  return unwrap(res, "list transactions");
}

const EXPORT_PAGE_LIMIT = 200;
const EXPORT_MAX_PAGES = 25; // caps a single export at 5,000 rows

// Walks keyset pagination to collect every row matching a filter — listTransactions
// alone only returns one page, which is fine for the table (it just wants "enough to
// show") but not for an export, which must be complete.
export async function fetchAllTransactions(filter: TransactionFilter): Promise<Transaction[]> {
  const items: Transaction[] = [];
  let cursor: string | undefined;

  for (let page = 0; page < EXPORT_MAX_PAGES; page++) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filter)) if (v) params.set(k, v);
    params.set("limit", String(EXPORT_PAGE_LIMIT));
    if (cursor) params.set("cursor", cursor);
    const res = await fetch(`/api/transactions/transactions?${params}`, { headers: await authHeaders() });
    const page_data = await unwrap<{ items: Transaction[]; next_cursor: string | null }>(res, "export transactions");
    items.push(...page_data.items);
    if (!page_data.next_cursor) break;
    cursor = page_data.next_cursor;
  }

  return items;
}

export async function patchTransaction(
  id: string,
  patch: Record<string, unknown>,
  idempotencyKey: string,
): Promise<Transaction> {
  const res = await fetch(`/api/transactions/transactions/${id}`, {
    method: "PATCH",
    headers: await authHeaders({ "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }),
    body: JSON.stringify(patch),
  });

  return unwrap(res, "patch transaction");
}

export async function deleteTransaction(id: string, idempotencyKey: string): Promise<{ deleted: string }> {
  const res = await fetch(`/api/transactions/transactions/${id}`, {
    method: "DELETE",
    headers: await authHeaders({ "Idempotency-Key": idempotencyKey }),
  });

  return unwrap(res, "delete transaction");
}

export async function createTransactionBatch(
  transactions: Array<Record<string, unknown>>,
  idempotencyKey: string,
): Promise<{ items: Transaction[] }> {
  const res = await fetch(`/api/transactions/transactions`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }),
    body: JSON.stringify({ transactions }),
  });

  return unwrap(res, "create transactions");
}

// --- chat ---------------------------------------------------------------------------

export async function listThreads(): Promise<{ items: ThreadSummary[] }> {
  const res = await fetch(`/api/chat/threads`, { headers: await authHeaders() });

  return unwrap(res, "list threads");
}

/** Records a confirmed receipt card in the thread, so its "saved N transactions"
 * message survives a reload and the model knows the receipt was saved. */
export async function recordReceiptSaved(threadId: string, count: number): Promise<void> {
  const res = await fetch(`/api/chat/threads/${threadId}/receipt-saved`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ count }),
  });

  if (!res.ok) throw new Error(`record receipt saved failed: ${res.status}`);
}

export async function getThreadMessages(
  threadId: string,
  opts?: { beforeSeq?: number; limit?: number },
): Promise<{ items: StoredMessage[]; has_more: boolean }> {
  const params = new URLSearchParams();
  if (opts?.beforeSeq !== undefined) params.set("before_seq", String(opts.beforeSeq));
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  const res = await fetch(`/api/chat/threads/${threadId}/messages${qs ? `?${qs}` : ""}`, {
    headers: await authHeaders(),
  });

  return unwrap(res, "get thread messages");
}

// The upload URL is only valid for this Content-Type (a signed URL in production), so
// the same type must be sent to both calls.
export async function requestUploadTarget(contentType: ReceiptContentType): Promise<UploadTarget> {
  const res = await fetch(`/api/chat/uploads`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ content_type: contentType }),
  });

  return unwrap(res, "request upload target");
}

export async function uploadReceiptImage(
  target: UploadTarget,
  body: Blob,
  contentType: ReceiptContentType,
): Promise<void> {
  const res = await fetch(target.url, {
    method: target.method,
    headers: { "Content-Type": contentType },
    body,
  });
  if (!res.ok) throw new Error(`upload failed: ${res.status}`);
}

// --- preferences ----------------------------------------------------------------------

export async function getPreferences(): Promise<Preferences> {
  const res = await fetch(`/api/chat/preferences`, { headers: await authHeaders() });

  return unwrap(res, "get preferences");
}

export async function updatePreferences(patch: { language: string }): Promise<Preferences> {
  const res = await fetch(`/api/chat/preferences`, {
    method: "PUT",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(patch),
  });

  return unwrap(res, "update preferences");
}

// --- voice input ------------------------------------------------------------------------

export async function transcribeAudio(blob: Blob): Promise<{ text: string }> {
  const form = new FormData();
  const ext = blob.type.includes("mp4") ? "mp4" : "webm";
  form.append("file", blob, `voice-message.${ext}`);
  // No Content-Type header here — the browser sets multipart/form-data with the
  // right boundary itself when the body is a FormData; setting it manually breaks it.
  const res = await fetch(`/api/chat/transcribe`, { method: "POST", headers: await authHeaders(), body: form });

  return unwrap(res, "transcribe audio");
}
