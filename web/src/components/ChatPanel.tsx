import { useQueryClient } from "@tanstack/react-query";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { createTransactionBatch, recordReceiptSaved, requestUploadTarget, uploadReceiptImage } from "../lib/api";
import type { TransactionFilter } from "../types/api";
import { errorDetail, messageText } from "../lib/chat";
import type { ProposedItem, ReceiptProposal } from "../types/chat";
import { useTranslation } from "../lib/i18n";
import { receiptViewUrlFromObject } from "../lib/receipts";
import { prepareReceiptUpload } from "../lib/receiptUpload";
import { useChatStream } from "../lib/useChatStream";
import { useThreadMessages } from "../lib/useThreadMessages";
import { useVoiceRecorder } from "../lib/useVoiceRecorder";
import { ChatBubble, ThinkingBubble } from "./ChatBubble";
import ChatComposer from "./ChatComposer";
import { Button } from "./ui/button";
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
  const { streaming, pendingText, pendingNotice, send } = useChatStream(threadId, filterRef, {
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
    onError: () => appendMessage({ role: "assistant", text: "", notice: { key: "micError" } }),
  });

  useEffect(() => {
    // Prepending older messages has its own scroll-position handling — jumping to the
    // bottom here would fight it.
    if (history.justLoadedOlderRef.current) {
      history.justLoadedOlderRef.current = false;

      return;
    }
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pendingText, pendingNotice, history.justLoadedOlderRef]);

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
    // the server (see services/agent/app/workflows/main.py), so don't pad it.
    const caption = input.trim();
    setInput("");
    setProposal(null); // clear any unconfirmed card from a previous upload
    const upload = await prepareReceiptUpload(file);
    const target = await requestUploadTarget(upload.contentType);
    await uploadReceiptImage(target, upload.body, upload.contentType);
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
      appendMessage({ role: "assistant", text: "", notice: { key: "saveFailed", params: { error: errorDetail(e) } } });

      return;
    }
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    setProposal(null);

    if (threadId) {
      recordReceiptSaved(threadId, proposal.items.length).catch(() => {
        // best effort — the transactions are saved; only the chat note is lost on reload
      });
    }

    appendMessage({
      role: "assistant",
      text: "",
      notice: { key: "savedTransactions", params: { n: String(proposal.items.length) } },
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
    <div className="flex min-h-0 flex-1 flex-col rounded-3xl bg-card shadow-sm ring-1 ring-foreground/5">
      <div
        ref={messageListRef}
        onScroll={(e) => {
          if (e.currentTarget.scrollTop < 80 && history.hasMoreOlder && !history.loadingOlder) {
            history.loadEarlierMessages();
          }
        }}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4"
      >
        {history.loadingOlder && <ThinkingBubble label={t("loadingEarlier")} />}
        {!history.loadingOlder && history.hasMoreOlder && (
          <Button variant="outline" className="self-center" onClick={history.loadEarlierMessages}>
            {t("loadEarlierMessages")}
          </Button>
        )}
        {messages.map((m, i) => {
          const text = messageText(m, t);

          return (
            <div key={i} className={`flex flex-col gap-1.5 ${m.role === "user" ? "items-end" : "items-start"}`}>
              {text && <ChatBubble role={m.role}>{text}</ChatBubble>}
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
          );
        })}
        {streaming && (pendingText || pendingNotice) && (
          <ChatBubble role="assistant">
            {messageText({ role: "assistant", text: pendingText, notice: pendingNotice }, t)}
          </ChatBubble>
        )}
        {streaming && !pendingText && !pendingNotice && <ThinkingBubble label={t("thinking")} />}
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
    </div>
  );
});

export default ChatPanel;
