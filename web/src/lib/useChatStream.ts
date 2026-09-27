import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { authHeaders, fetchAllTransactions } from "./api";
import type { TransactionFilter } from "../types/api";
import { toNotice, toReceiptProposal } from "./chat";
import type { DisplayMessage, Notice, ReceiptProposal } from "../types/chat";
import { createCsvObjectUrl } from "./csv";
import { defaultFilter, exportFilename } from "./filters";

interface Callbacks {
  onMessage: (message: DisplayMessage) => void; // the user's message, then the final reply
  onThreadId: (id: string) => void;
  onFilterSet: (filter: TransactionFilter) => void;
  onReceiptProposed: (proposal: ReceiptProposal) => void;
}

/** Sends one chat turn and turns the server's SSE events into UI state: the reply
 * streaming in (`pendingText`, plus `pendingNotice` for a fixed reply), table refreshes, filter changes, a receipt proposal,
 * and a CSV attachment when the turn exported. */
export function useChatStream(threadId: string | null, filterRef: RefObject<TransactionFilter>, callbacks: Callbacks) {
  const [streaming, setStreaming] = useState(false);
  const [pendingText, setPendingText] = useState("");
  const [pendingNotice, setPendingNotice] = useState<Notice | undefined>(undefined);
  // Read inside the SSE callbacks, which outlive the render that started the send.
  const threadIdRef = useRef(threadId);
  useEffect(() => {
    threadIdRef.current = threadId;
  }, [threadId]);
  const queryClient = useQueryClient();

  async function send(message: string, receiptObject?: string, receiptImageUrl?: string) {
    if (!message.trim() && !receiptObject) return;
    callbacks.onMessage({ role: "user", text: message, imageUrl: receiptImageUrl });
    setStreaming(true);
    setPendingText("");
    setPendingNotice(undefined);

    const headers = await authHeaders({ "Content-Type": "application/json" });
    let assistantText = "";
    let notice: Notice | undefined;
    let exportRequested = false;

    try {
      await fetchEventSource("/api/chat/chat", {
        method: "POST",
        headers,
        body: JSON.stringify({
          thread_id: threadIdRef.current,
          message,
          client_msg_id: crypto.randomUUID(),
          receipt_object: receiptObject,
          // So "today"/"yesterday" and receipt dates resolve in the user's timezone,
          // not the server's (UTC).
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
        openWhenHidden: true,
        onmessage(ev) {
          if (!ev.data) return;
          const data = JSON.parse(ev.data);
          const kind = ev.event || "message";

          if (kind === "message" && data.type === "token") {
            assistantText += data.text;
            setPendingText(assistantText);
          } else if (kind === "reset_pending") {
            // What streamed so far was narration before a tool call ("I'll export
            // this now."), not the final answer — drop it so it doesn't run into the
            // real answer that follows with no separator.
            assistantText = "";
            setPendingText("");
          } else if (kind === "table_changed") {
            // The agent changed the table: refresh it now, not at the next refetch.
            queryClient.invalidateQueries({ queryKey: ["transactions"] });
          } else if (kind === "filter_set") {
            // An empty filter from set_filter means "clear" — back to the default view.
            const f = data.filter ?? {};
            const resolved = Object.keys(f).length > 0 ? f : defaultFilter();
            // Updated synchronously: an export later in this same turn must see it,
            // and the `filter` prop won't until React re-renders.
            filterRef.current = resolved;
            callbacks.onFilterSet(resolved);
          } else if (kind === "export_ready") {
            // fetchEventSource doesn't await onmessage, so a fetch started here could
            // outlive the stream. Flag it; the CSV is built after the stream ends.
            exportRequested = true;
          } else if (kind === "receipt_proposed") {
            callbacks.onReceiptProposed(toReceiptProposal(data));
          } else if (kind === "notice") {
            // A fixed reply (e.g. a receipt read), sent as a key — shown translated.
            notice = toNotice(data);
            setPendingNotice(notice);
          } else if (kind === "done") {
            if (!threadIdRef.current) callbacks.onThreadId(data.thread_id);
          } else if (kind === "error") {
            // Shown like normal reply text, after anything already streamed.
            notice = toNotice(data.notice) ?? { key: "requestFailed" };
            setPendingNotice(notice);
          }
        },
        onerror(err) {
          throw err; // fetchEventSource retries forever unless the handler throws
        },
      });
    } finally {
      setStreaming(false);
      let csvAttachment: { csvUrl?: string; csvFilename?: string } = {};

      if (exportRequested) {
        try {
          const items = await fetchAllTransactions(filterRef.current);
          csvAttachment = { csvUrl: createCsvObjectUrl(items), csvFilename: exportFilename() };
        } catch {
          // best effort — the assistant's own text still told the user an export happened
        }
      }
      if (!assistantText && !notice) notice = { key: "noResponse" };
      callbacks.onMessage({ role: "assistant", text: assistantText, notice, ...csvAttachment });
      setPendingText("");
      setPendingNotice(undefined);
    }
  }

  return { streaming, pendingText, pendingNotice, send };
}
