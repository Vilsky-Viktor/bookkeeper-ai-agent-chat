import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useQueryClient } from "@tanstack/react-query";
import { Paperclip, Send } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  authHeaders,
  createTransactionBatch,
  fetchAllTransactions,
  getThreadMessages,
  requestUploadTarget,
  uploadReceiptImage,
} from "../lib/api";
import type { TransactionFilter } from "../lib/api";
import { createCsvObjectUrl } from "../lib/csv";
import { defaultFilter, exportFilename } from "../lib/filters";
import { useTranslation } from "../lib/i18n";
import { receiptViewUrlFromObject, splitReceiptMarker } from "../lib/receipts";
import FileAttachment from "./FileAttachment";
import ReceiptThumb from "./ReceiptThumb";
import Tooltip from "./Tooltip";

interface DisplayMessage {
  role: "user" | "assistant";
  text: string;
  imageUrl?: string;
  csvUrl?: string;
  csvFilename?: string;
}

interface ProposedItem {
  occurred_on: string;
  type: string;
  amount: string;
  currency: string;
  category: string;
  description: string | null;
  receipt_uri: string;
}

interface Props {
  threadId: string | null;
  onThreadId: (id: string) => void;
  filter: TransactionFilter;
  onFilterSet: (f: TransactionFilter) => void;
  onViewImage: (url: string) => void;
}

export interface ChatPanelHandle {
  // Lets TransactionsTable's reference button drop a transaction id into the message
  // box — App.tsx mediates since the table and the panel are siblings. The bracketed
  // marker mirrors "[uploaded receipt: ...]" (see splitReceiptMarker) so the model can
  // resolve it to an exact transaction_id even when it was never mentioned in chat and
  // so isn't in the working set yet.
  insertReference: (id: string) => void;
}

const proposedInputClass =
  "rounded-md border border-zinc-200 bg-white px-1.5 py-1 text-xs text-zinc-900 focus:outline-none focus:ring-1 focus:ring-zinc-400/40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:focus:ring-zinc-400/40";

const ChatPanel = forwardRef<ChatPanelHandle, Props>(function ChatPanel(
  { threadId, onThreadId, filter, onFilterSet, onViewImage },
  ref,
) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [pendingText, setPendingText] = useState("");
  const [proposed, setProposed] = useState<{ items: ProposedItem[]; receipt_uri: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textInputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const threadIdRef = useRef(threadId);
  threadIdRef.current = threadId;
  // A ref, not a closure read of the `filter` prop — set_filter and export can be
  // called in the same turn, and React state updates from the filter_set handler
  // below wouldn't be visible yet inside that same synchronous onmessage callback.
  const filterRef = useRef(filter);
  filterRef.current = filter;
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  useEffect(() => {
    // Thread history is loaded fresh on mount; new turns append to local state as
    // they stream in (see architecture doc, p. 9: "UI loads messages on open, renders
    // full history from the database. What the model sees is built separately.").
    if (!threadId) {
      setMessages([]);
      return;
    }
    getThreadMessages(threadId).then(async (res) => {
      const loaded: DisplayMessage[] = [];
      // Indexes of assistant messages whose turn called export_transactions — the CSV
      // itself is a client-side blob (see confirmReceipt/send's csvAttachment), never
      // persisted server-side, so after a reload the text still says "click the file
      // below" but the file is gone. Rebuild it from a fresh export instead of leaving
      // that sentence pointing at nothing.
      const exportIndexes: number[] = [];
      for (const m of res.items) {
        if (m.role === "user" && m.content?.text) {
          // The stored text carries a "[uploaded receipt: ...]" marker when a receipt
          // was attached (see main.py) — split it back into text + a viewable image.
          loaded.push({ role: "user", ...splitReceiptMarker(m.content.text) });
        } else if (m.role === "assistant" && m.content?.text) {
          const toolCalls = m.content.tool_calls as { name?: string }[] | undefined;
          if (toolCalls?.some((c) => c.name === "export_transactions")) exportIndexes.push(loaded.length);
          loaded.push({ role: "assistant", text: m.content.text });
        }
      }
      setMessages(loaded);
      if (exportIndexes.length === 0) return;
      try {
        const items = await fetchAllTransactions(filterRef.current);
        const csvUrl = createCsvObjectUrl(items);
        const csvFilename = exportFilename();
        setMessages((cur) => cur.map((m, i) => (exportIndexes.includes(i) ? { ...m, csvUrl, csvFilename } : m)));
      } catch {
        // best effort — the message text still reads fine even without a file to click
      }
    });
  }, [threadId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pendingText]);

  useEffect(() => {
    // The input is disabled (and loses focus) while a turn streams; once it's
    // enabled again, put focus back so the next message can be typed immediately
    // without reaching for the mouse.
    if (!streaming) textInputRef.current?.focus();
  }, [streaming]);

  async function send(message: string, receiptObject?: string, receiptImageUrl?: string) {
    if (!message.trim() && !receiptObject) return;
    setMessages((m) => [...m, { role: "user", text: message, imageUrl: receiptImageUrl }]);
    setStreaming(true);
    setPendingText("");

    const headers = await authHeaders({ "Content-Type": "application/json" });
    let assistantText = "";
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
            // Same-tab update: the Firestore signal skips this tab (origin match), so
            // the SSE event itself is what triggers the refetch here (architecture
            // doc, Live updates > Same tab vs other clients, p. 12).
            queryClient.invalidateQueries({ queryKey: ["transactions"] });
          } else if (kind === "filter_set") {
            // An empty filter from set_filter means "clear" — that resets to the
            // current-month default, not to showing every transaction ever.
            const f = data.filter ?? {};
            const resolved = Object.keys(f).length > 0 ? f : defaultFilter();
            // Update the ref synchronously — set_filter and export can both be called
            // within this same turn, and the `filter` prop won't reflect this update
            // until React re-renders, which is too late for an export event that
            // follows later in this same onmessage callback.
            filterRef.current = resolved;
            onFilterSet(resolved);
          } else if (kind === "export_ready") {
            // fetchEventSource doesn't await onmessage (confirmed in its source —
            // getMessages calls onMessage synchronously, fire-and-forget), so an
            // async fetch started here wouldn't reliably finish before the stream
            // ends and the `finally` block runs. Just flag it; the actual fetch
            // happens after the stream completes, below.
            exportRequested = true;
          } else if (kind === "receipt_proposed") {
            setProposed({ items: data.items, receipt_uri: data.receipt_uri });
          } else if (kind === "done") {
            if (!threadIdRef.current) onThreadId(data.thread_id);
          } else if (kind === "error") {
            // The server always sends a plain, conversational sentence here (never a
            // raw technical error) — render it like normal reply text, not a tag.
            assistantText += (assistantText ? "\n" : "") + data.message;
            setPendingText(assistantText);
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
          // best-effort — the assistant's own text still told the user an export happened
        }
      }
      setMessages((m) => [...m, { role: "assistant", text: assistantText || "(no response)", ...csvAttachment }]);
      setPendingText("");
    }
  }

  async function handleSendClick() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    await send(text);
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const caption = input.trim() || t("extractReceiptCaption");
    setInput("");
    setProposed(null); // clear any unconfirmed card from a previous upload
    const target = await requestUploadTarget();
    await uploadReceiptImage(target, file);
    const imageUrl = receiptViewUrlFromObject(target.object);
    await send(caption, target.object, imageUrl ?? undefined);
  }

  async function confirmReceipt() {
    if (!proposed) return;
    await createTransactionBatch(proposed.items as unknown as Record<string, unknown>[], crypto.randomUUID());
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    setProposed(null);
    setMessages((m) => [
      ...m,
      { role: "assistant", text: t("savedTransactions").replace("{n}", String(proposed.items.length)) },
    ]);
  }

  function updateProposedItem(idx: number, field: keyof ProposedItem, value: string) {
    setProposed((p) => {
      if (!p) return p;
      const items = [...p.items];
      items[idx] = { ...items[idx], [field]: value };
      return { ...p, items };
    });
  }

  useImperativeHandle(ref, () => ({
    insertReference(id: string) {
      const marker = `[transaction: ${id}]`;
      setInput((cur) => (cur.trim() ? `${cur.trim()} ${marker} ` : `${marker} `));
      textInputRef.current?.focus();
    },
  }));

  return (
    <>
      <div className="flex flex-1 flex-col gap-2.5 overflow-y-auto p-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex max-w-[90%] flex-col gap-1.5 ${m.role === "user" ? "self-end items-end" : "self-start items-start"}`}>
            <div
              className={`whitespace-pre-wrap rounded-xl px-3 py-2 text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-zinc-600 text-white dark:bg-zinc-300 dark:text-zinc-900"
                  : "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
              }`}
            >
              {m.text}
            </div>
            {m.imageUrl && (
              <ReceiptThumb
                url={m.imageUrl}
                onView={onViewImage}
                // Images load async and grow the container after the scroll-to-bottom
                // effect below already ran against the shorter, pre-image layout —
                // without this the view lands just short of the real bottom.
                onLoad={() => messagesEndRef.current?.scrollIntoView({ behavior: "auto" })}
              />
            )}
            {m.csvUrl && m.csvFilename && <FileAttachment url={m.csvUrl} filename={m.csvFilename} />}
          </div>
        ))}
        {streaming && pendingText && (
          <div className="max-w-[90%] self-start whitespace-pre-wrap rounded-xl bg-zinc-100 px-3 py-2 text-sm leading-relaxed text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100">
            {pendingText}
          </div>
        )}
        {streaming && !pendingText && (
          <div className="self-center text-xs text-zinc-400 dark:text-zinc-500">
            <span className="animate-pulse">{t("thinking")}</span>
          </div>
        )}

        {proposed && (
          <div className="rounded-xl border border-dashed border-zinc-300 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-900/50">
            <strong className="mb-2.5 block text-sm font-medium text-zinc-900 dark:text-zinc-100">
              {t("receiptFoundHeading")}
            </strong>
            {proposed.items.map((item, i) => (
              <div className="flex items-center gap-1.5 py-1 text-sm" key={i}>
                <input
                  value={item.description ?? ""}
                  onChange={(e) => updateProposedItem(i, "description", e.target.value)}
                  className={`${proposedInputClass} flex-1`}
                />
                <input
                  value={item.amount}
                  onChange={(e) => updateProposedItem(i, "amount", e.target.value)}
                  className={`${proposedInputClass} w-[60px]`}
                />
                <input
                  value={item.currency}
                  onChange={(e) => updateProposedItem(i, "currency", e.target.value.toUpperCase())}
                  className={`${proposedInputClass} w-[45px]`}
                />
                <input
                  value={item.category}
                  onChange={(e) => updateProposedItem(i, "category", e.target.value)}
                  className={`${proposedInputClass} w-[80px]`}
                />
              </div>
            ))}
            <div className="mt-2 flex gap-2">
              <button
                onClick={confirmReceipt}
                className="rounded-lg bg-zinc-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-zinc-500 dark:bg-zinc-300 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                {t("confirmAndSave")}
              </button>
              <button
                onClick={() => setProposed(null)}
                className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                {t("cancel")}
              </button>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="relative z-10 border-t border-zinc-200 p-2.5 shadow-[0_-4px_6px_-1px_rgb(0_0_0_/_0.05),0_-2px_4px_-2px_rgb(0_0_0_/_0.05)] dark:border-zinc-800">
        <div className="relative">
          <textarea
            ref={textInputRef}
            rows={4}
            placeholder={t("chatPlaceholder")}
            value={input}
            disabled={streaming}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !streaming) {
                e.preventDefault(); // Enter sends; Shift+Enter for a newline
                handleSendClick();
              }
            }}
            className="w-full resize-none rounded-lg border border-zinc-200 bg-white py-2 ps-3 pe-12 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-400/40 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-500 dark:focus:ring-zinc-400/40"
          />
          <input
            type="file"
            accept="image/*,application/pdf"
            ref={fileInputRef}
            className="hidden"
            onChange={handleFileChange}
          />
          <div className="absolute end-2 top-1/2 flex -translate-y-1/2 flex-col gap-1.5">
            <Tooltip label={t("uploadReceipt")} align="end">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={streaming}
                aria-label={t("uploadReceipt")}
                className="flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-800"
              >
                <Paperclip size={18} />
              </button>
            </Tooltip>
            <Tooltip label={t("send")} align="end">
              <button
                onClick={handleSendClick}
                disabled={streaming || !input.trim()}
                aria-label={t("send")}
                className="flex h-8 w-8 items-center justify-center rounded-md bg-zinc-600 text-white transition-colors hover:bg-zinc-500 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-300 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                <Send size={17} />
              </button>
            </Tooltip>
          </div>
        </div>
      </div>
    </>
  );
});

export default ChatPanel;
