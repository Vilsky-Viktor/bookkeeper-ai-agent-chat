// Turns a stored receipt reference into a browser-viewable URL, through Caddy's
// /gcs/* route to fake-gcs-server (see Caddyfile, STORAGE_MODE=local in
// services/agent/app/storage.py). Local-dev only: a production build would need this
// resolved server-side into a signed GET URL instead.

// Matches RECEIPTS_BUCKET in docker-compose.yml — set via a build-time env var so
// this file doesn't have to special-case "we just uploaded it" vs "loaded from
// history", both of which only ever know the bare object path.
const BUCKET = import.meta.env.VITE_RECEIPTS_BUCKET || "receipts-local";

function buildUrl(bucket: string, object: string): string {
  return `/gcs/download/storage/v1/b/${bucket}/o/${encodeURIComponent(object)}?alt=media`;
}

// From a full receipt_uri as stored on a transaction row, e.g. "gs://bucket/object".
export function receiptViewUrl(receiptUri: string | null | undefined): string | null {
  if (!receiptUri) return null;
  const match = receiptUri.match(/^gs:\/\/([^/]+)\/(.+)$/);
  if (!match) return null;
  const [, bucket, object] = match;
  return buildUrl(bucket, object);
}

// From a bare object path, e.g. "receipts/<uid>/<id>.jpg" — what we have right after
// an upload, and what's embedded in a chat message's "[uploaded receipt: ...]" marker.
export function receiptViewUrlFromObject(object: string | null | undefined): string | null {
  if (!object) return null;
  return buildUrl(BUCKET, object);
}

const RECEIPT_MARKER = /\n\n\[uploaded receipt: (.+?)\]$/;

// The backend appends "\n\n[uploaded receipt: <object>]" to a user message's stored
// text when a receipt was attached (see services/agent/app/main.py). Splits that back
// into display text + a viewable image URL, for reconstructing history after reload —
// the live-send path already has the image url in hand and never needed this.
export function splitReceiptMarker(text: string): { text: string; imageUrl?: string } {
  const match = text.match(RECEIPT_MARKER);
  if (!match) return { text };
  const imageUrl = receiptViewUrlFromObject(match[1]);
  return { text: text.slice(0, match.index), imageUrl: imageUrl ?? undefined };
}
