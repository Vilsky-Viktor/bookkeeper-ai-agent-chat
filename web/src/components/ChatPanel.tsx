import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useQueryClient } from "@tanstack/react-query";
import { Mic, Paperclip, Sparkles, Square } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  authHeaders,
  createTransactionBatch,
  fetchAllTransactions,
  getThreadMessages,
  requestUploadTarget,
  transcribeAudio,
  uploadReceiptImage,
} from "../lib/api";
import type { StoredMessage, TransactionFilter } from "../lib/api";
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
  // Only set for messages loaded from history (not ones just sent locally) — used to
  // paginate further back via before_seq. See loadEarlierMessages.
  seq?: number;
}

// Matches the backend default (see get_messages in main.py) so the first page and
// each "load earlier" page fetch the same amount.
const MESSAGE_PAGE_LIMIT = 50;

function mapStoredMessages(items: StoredMessage[]): DisplayMessage[] {
  const mapped: DisplayMessage[] = [];
  for (const m of items) {
    if (m.role === "user" && m.content?.text) {
      // The stored text carries a "[uploaded receipt: ...]" marker when a receipt was
      // attached (see main.py) — split it back into text + a viewable image.
      mapped.push({ role: "user", seq: m.seq, ...splitReceiptMarker(m.content.text) });
    } else if (m.role === "assistant" && m.content?.text) {
      mapped.push({ role: "assistant", seq: m.seq, text: m.content.text });
    }
  }
  return mapped;
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
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [hasMoreOlder, setHasMoreOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textInputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const justLoadedOlderRef = useRef(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  // A ref, not a closure read of `input` — recording can run for a while and the
  // onstop handler below is created once at recording start, so a plain closure
  // would send whatever was typed at that moment, not anything typed since.
  const inputRef = useRef(input);
  inputRef.current = input;
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
    setHasMoreOlder(false);
    getThreadMessages(threadId, { limit: MESSAGE_PAGE_LIMIT }).then(async (res) => {
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
          loaded.push({ role: "user", seq: m.seq, ...splitReceiptMarker(m.content.text) });
        } else if (m.role === "assistant" && m.content?.text) {
          const toolCalls = m.content.tool_calls;
          if (toolCalls?.some((c) => c.name === "export_transactions")) exportIndexes.push(loaded.length);
          loaded.push({ role: "assistant", seq: m.seq, text: m.content.text });
        }
      }
      setMessages(loaded);
      setHasMoreOlder(res.has_more);
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

  async function loadEarlierMessages() {
    const oldestSeq = messages[0]?.seq;
    if (!threadId || loadingOlder || !hasMoreOlder || oldestSeq === undefined) return;
    setLoadingOlder(true);
    try {
      const res = await getThreadMessages(threadId, { beforeSeq: oldestSeq, limit: MESSAGE_PAGE_LIMIT });
      const older = mapStoredMessages(res.items);
      const container = messageListRef.current;
      const prevScrollHeight = container?.scrollHeight ?? 0;
      justLoadedOlderRef.current = true;
      setMessages((cur) => [...older, ...cur]);
      setHasMoreOlder(res.has_more);
      // Prepending content pushes everything down — without this the view jumps to
      // the top instead of staying where the user was reading.
      requestAnimationFrame(() => {
        if (container) container.scrollTop += container.scrollHeight - prevScrollHeight;
      });
    } finally {
      setLoadingOlder(false);
    }
  }

  function handleMessageListScroll(e: React.UIEvent<HTMLDivElement>) {
    if (e.currentTarget.scrollTop < 80 && hasMoreOlder && !loadingOlder) {
      loadEarlierMessages();
    }
  }

  useEffect(() => {
    // Prepending older messages (loadEarlierMessages) also changes `messages`, but it
    // has its own scroll-position handling — jumping to the bottom here would fight it.
    if (justLoadedOlderRef.current) {
      justLoadedOlderRef.current = false;
      return;
    }
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

  // Press-and-hold, not click-to-toggle: holdingRef tracks whether the pointer is
  // still down through the async getUserMedia gap, so a very quick tap (released
  // before the mic permission prompt/resolve even finishes) doesn't leave recording
  // stuck on with nothing to stop it.
  const holdingRef = useRef(false);

  async function startRecording() {
    holdingRef.current = true;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setMessages((m) => [...m, { role: "assistant", text: t("micError") }]);
      holdingRef.current = false;
      return;
    }
    if (!holdingRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    const mimeType = ["audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    audioChunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data);
    };
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      setRecording(false);
      const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
      if (blob.size === 0) return;
      setTranscribing(true);
      try {
        const { text } = await transcribeAudio(blob);
        if (text.trim()) {
          const combined = inputRef.current.trim() ? `${inputRef.current.trim()} ${text.trim()}` : text.trim();
          setInput("");
          setTranscribing(false);
          await send(combined);
          return;
        }
      } catch {
        setMessages((m) => [...m, { role: "assistant", text: t("micError") }]);
      }
      setTranscribing(false);
      textInputRef.current?.focus();
    };
    mediaRecorderRef.current = recorder;
    recorder.start();
    setRecording(true);
  }

  function handleMicPointerDown(e: React.PointerEvent<HTMLButtonElement>) {
    e.preventDefault(); // don't steal focus from the textarea or trigger text selection
    e.currentTarget.setPointerCapture(e.pointerId);
    startRecording();
  }

  function handleMicPointerUp(e: React.PointerEvent<HTMLButtonElement>) {
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      // already released
    }
    holdingRef.current = false;
    mediaRecorderRef.current?.stop();
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
      <div
        ref={messageListRef}
        onScroll={handleMessageListScroll}
        className="flex flex-1 flex-col gap-2.5 overflow-y-auto p-3"
      >
        {loadingOlder && (
          <div className="flex items-center justify-center gap-2 self-center py-1 text-xs text-zinc-400 dark:text-zinc-500">
            <Sparkles size={14} className="animate-pulse" />
            <span className="animate-pulse">{t("loadingEarlier")}</span>
          </div>
        )}
        {!loadingOlder && hasMoreOlder && (
          <button
            onClick={loadEarlierMessages}
            className="self-center rounded-full border border-zinc-200 px-3 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
          >
            {t("loadEarlierMessages")}
          </button>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex max-w-[90%] flex-col gap-1.5 ${m.role === "user" ? "self-end items-end" : "self-start items-start"}`}
          >
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
          <div className="mt-1.5 flex items-center gap-2 self-center text-base text-zinc-400 dark:text-zinc-500">
            <Sparkles size={18} className="animate-pulse" />
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
      <div className="relative z-10 border-t border-zinc-200 pt-4 pb-8 ps-8 pe-8 shadow-[0_-4px_6px_-1px_rgb(0_0_0_/_0.05),0_-2px_4px_-2px_rgb(0_0_0_/_0.05)] dark:border-zinc-800">
        {transcribing && (
          <div className="mb-1.5 flex items-center justify-center gap-2 text-base text-zinc-400 dark:text-zinc-500">
            <Mic size={18} className="animate-pulse" />
            <span className="animate-pulse">{t("transcribing")}</span>
          </div>
        )}
        <div className="relative">
          {/* The rounded/bordered frame is a separate element from the <textarea> —
              the textarea's own box stops well above the frame's bottom edge, with a
              fixed dead-space strip between them that's never part of the scrollable
              text area. A textarea's padding-bottom alone isn't safe for this: once
              typed content overflows, the browser auto-scrolls to keep the caret in
              view and doesn't keep trailing padding on screen, so text would
              eventually scroll up underneath the corner buttons. Making the dead
              space a real sibling element, outside the textarea's box entirely, means
              no scroll position can ever put text there. */}
          <div className="rounded-lg border border-zinc-200 bg-white focus-within:ring-2 focus-within:ring-zinc-400/40 dark:border-zinc-700 dark:bg-zinc-900">
            <textarea
              ref={textInputRef}
              rows={4}
              placeholder={t("chatPlaceholder")}
              value={input}
              disabled={streaming || transcribing}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !streaming) {
                  e.preventDefault(); // Enter sends; Shift+Enter for a newline
                  handleSendClick();
                }
              }}
              className="block w-full resize-none border-0 bg-transparent pt-2 ps-3 pe-3 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none disabled:opacity-50 dark:text-zinc-100 dark:placeholder-zinc-500"
            />
            <div className="h-10" aria-hidden="true" />
          </div>
          <input
            type="file"
            accept="image/*,application/pdf"
            ref={fileInputRef}
            className="hidden"
            onChange={handleFileChange}
          />
          {/* Attach and Mic are big circles straddling the input's bottom corners —
              half in, half out — Send stays inline, above the mic circle, so the two
              don't collide. The absolute positioning lives on a wrapper OUTSIDE each
              Tooltip, not on the button itself — Tooltip's own root is `relative`
              (so its tooltip bubble anchors to the button), and that would otherwise
              become the positioning context instead of this textarea wrapper. */}
          <div className="absolute bottom-0 start-0 translate-x-[-35%] translate-y-[35%]">
            <Tooltip label={t("uploadReceipt")} align="start">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={streaming || recording || transcribing}
                aria-label={t("uploadReceipt")}
                className="flex h-12 w-12 items-center justify-center rounded-full bg-white text-zinc-500 shadow-md ring-1 ring-zinc-200 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-800 dark:text-zinc-400 dark:ring-zinc-700 dark:hover:bg-zinc-700"
              >
                <Paperclip size={20} />
              </button>
            </Tooltip>
          </div>
          <div className="absolute bottom-0 end-0 translate-x-[35%] translate-y-[35%]">
            <Tooltip label={recording ? t("stopRecording") : t("recordVoice")} align="end">
              <button
                onPointerDown={handleMicPointerDown}
                onPointerUp={handleMicPointerUp}
                onPointerCancel={handleMicPointerUp}
                onContextMenu={(e) => e.preventDefault()}
                disabled={streaming || transcribing}
                aria-label={recording ? t("stopRecording") : t("recordVoice")}
                className={
                  recording
                    ? "flex h-12 w-12 animate-pulse touch-none select-none items-center justify-center rounded-full bg-red-600 text-white shadow-md transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                    : "flex h-12 w-12 touch-none select-none items-center justify-center rounded-full bg-white text-zinc-500 shadow-md ring-1 ring-zinc-200 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-800 dark:text-zinc-400 dark:ring-zinc-700 dark:hover:bg-zinc-700"
                }
              >
                {recording ? <Square size={17} fill="currentColor" /> : <Mic size={22} />}
              </button>
            </Tooltip>
          </div>
        </div>
      </div>
    </>
  );
});

export default ChatPanel;
