import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { createTransactionBatch, requestUploadTarget, uploadReceiptImage } from "../lib/api";
import type { TransactionFilter } from "../lib/api";
import { errorDetail } from "../lib/chat";
import type { ProposedItem, ReceiptProposal } from "../lib/chat";
import { useTranslation } from "../lib/i18n";
import { receiptViewUrlFromObject } from "../lib/receipts";
import { useChatStream } from "../lib/useChatStream";
import { useThreadMessages } from "../lib/useThreadMessages";
import { useVoiceRecorder } from "../lib/useVoiceRecorder";
import ChatComposer from "./ChatComposer";
import FileAttachment from "./FileAttachment";
import ReceiptProposalCard from "./ReceiptProposalCard";
import ReceiptThumb from "./ReceiptThumb";

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

const ChatPanel = forwardRef<ChatPanelHandle, Props>(function ChatPanel(
  { threadId, onThreadId, filter, onFilterSet, onViewImage },
  ref,
) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [proposal, setProposal] = useState<ReceiptProposal | null>(null);
  const textInputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  // Refs, not closure reads: a recording's transcript is sent long after it started,
  // and set_filter + export can happen in one turn before React re-renders.
  const inputRef = useRef(input);
  const filterRef = useRef(filter);
  useEffect(() => {
    inputRef.current = input;
  }, [input]);
  useEffect(() => {
    filterRef.current = filter;
  }, [filter]);

  const history = useThreadMessages(threadId, filterRef, messageListRef);
  const { messages, appendMessage } = history;
  const { streaming, pendingText, send } = useChatStream(threadId, filterRef, {
    onMessage: appendMessage,
    onThreadId,
    onFilterSet,
    onReceiptProposed: setProposal,
  });
  const voice = useVoiceRecorder({
    onTranscript: async (text) => {
      const typed = inputRef.current.trim();
      setInput("");
      await send(typed ? `${typed} ${text}` : text);
    },
    onError: () => appendMessage({ role: "assistant", text: t("micError") }),
  });

  useEffect(() => {
    // Prepending older messages has its own scroll-position handling — jumping to the
    // bottom here would fight it.
    if (history.justLoadedOlderRef.current) {
      history.justLoadedOlderRef.current = false;
      return;
    }
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pendingText, history.justLoadedOlderRef]);

  useEffect(() => {
    // The textarea is disabled (and loses focus) while a turn streams or a recording
    // transcribes; refocus afterwards so the next message can be typed right away.
    if (!streaming && !voice.transcribing) textInputRef.current?.focus();
  }, [streaming, voice.transcribing]);

  async function handleSend() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    await send(text);
  }

  async function handleFileSelected(file: File) {
    // Sent as typed, possibly empty: an upload with no text skips the chat model on
    // the server (see services/agent/app/chat/receipt_turn.py), so don't pad it.
    const caption = input.trim();
    setInput("");
    setProposal(null); // clear any unconfirmed card from a previous upload
    const target = await requestUploadTarget();
    await uploadReceiptImage(target, file);
    await send(caption, target.object, receiptViewUrlFromObject(target.object) ?? undefined);
  }

  function updateProposedItem(index: number, field: keyof ProposedItem, value: string) {
    setProposal(
      (p) => p && { ...p, items: p.items.map((item, i) => (i === index ? { ...item, [field]: value } : item)) },
    );
  }

  async function confirmProposal() {
    if (!proposal) return;
    try {
      await createTransactionBatch(proposal.items as unknown as Record<string, unknown>[], crypto.randomUUID());
    } catch (e) {
      // Keep the card so the user can fix the field the server rejected and retry.
      appendMessage({ role: "assistant", text: t("saveFailed").replace("{error}", errorDetail(e)) });
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    setProposal(null);
    appendMessage({ role: "assistant", text: t("savedTransactions").replace("{n}", String(proposal.items.length)) });
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
        onScroll={(e) => {
          if (e.currentTarget.scrollTop < 80 && history.hasMoreOlder && !history.loadingOlder) {
            history.loadEarlierMessages();
          }
        }}
        className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto rounded-xl bg-white p-3 shadow-sm dark:bg-zinc-900"
      >
        {history.loadingOlder && (
          <div className="flex items-center justify-center gap-2 self-center py-1 text-xs text-zinc-400 dark:text-zinc-600">
            <Sparkles size={14} className="animate-pulse" />
            <span className="animate-pulse">{t("loadingEarlier")}</span>
          </div>
        )}
        {!history.loadingOlder && history.hasMoreOlder && (
          <button
            onClick={history.loadEarlierMessages}
            className="self-center rounded-full border border-sky-200 px-3 py-1 text-xs font-medium text-sky-700 transition-colors hover:bg-sky-50 dark:border-sky-900 dark:text-sky-300 dark:hover:bg-sky-950/40"
          >
            {t("loadEarlierMessages")}
          </button>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex max-w-[90%] flex-col gap-1.5 ${m.role === "user" ? "self-end items-end" : "self-start items-start"}`}
          >
            {m.text && (
              <div
                className={`whitespace-pre-wrap rounded-xl px-3 py-2 text-sm leading-relaxed ${
                  m.role === "user"
                    ? "bg-sky-200 text-sky-900 dark:bg-sky-900/70 dark:text-sky-100"
                    : "bg-zinc-100 text-zinc-900 dark:bg-zinc-800/80 dark:text-zinc-100"
                }`}
              >
                {m.text}
              </div>
            )}
            {m.imageUrl && (
              <ReceiptThumb
                url={m.imageUrl}
                onView={onViewImage}
                // The image loads after the scroll-to-bottom effect already ran against
                // the shorter layout — scroll again once it has its real height.
                onLoad={() => messagesEndRef.current?.scrollIntoView({ behavior: "auto" })}
              />
            )}
            {m.csvUrl && m.csvFilename && <FileAttachment url={m.csvUrl} filename={m.csvFilename} />}
          </div>
        ))}
        {streaming && pendingText && (
          <div className="max-w-[90%] self-start whitespace-pre-wrap rounded-xl bg-zinc-100 px-3 py-2 text-sm leading-relaxed text-zinc-900 dark:bg-zinc-800/80 dark:text-zinc-100">
            {pendingText}
          </div>
        )}
        {streaming && !pendingText && (
          <div className="mt-1.5 flex items-center gap-2 self-center text-base text-zinc-400 dark:text-zinc-600">
            <Sparkles size={18} className="animate-pulse" />
            <span className="animate-pulse">{t("thinking")}</span>
          </div>
        )}
        {proposal && (
          <ReceiptProposalCard
            proposal={proposal}
            onChange={updateProposedItem}
            onConfirm={confirmProposal}
            onCancel={() => setProposal(null)}
          />
        )}
        <div ref={messagesEndRef} />
      </div>
      <ChatComposer
        value={input}
        onChange={setInput}
        onSend={handleSend}
        onFileSelected={handleFileSelected}
        textareaRef={textInputRef}
        streaming={streaming}
        recording={voice.recording}
        transcribing={voice.transcribing}
        micButtonProps={voice.micButtonProps}
      />
    </>
  );
});

export default ChatPanel;
