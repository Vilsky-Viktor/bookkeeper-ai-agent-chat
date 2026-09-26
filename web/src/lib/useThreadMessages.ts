import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { fetchAllTransactions, getThreadMessages } from "./api";
import type { TransactionFilter } from "./api";
import { mapStoredMessages } from "./chat";
import type { DisplayMessage } from "./chat";
import { createCsvObjectUrl } from "./csv";
import { exportFilename } from "./filters";

// Matches the backend default (see get_messages in main.py) so the first page and
// each "load earlier" page fetch the same amount.
const MESSAGE_PAGE_LIMIT = 50;

/** A thread's displayed history: loads the newest page when the thread changes,
 * pages further back on demand (keeping the reader's scroll position), and lets the
 * caller append messages as a turn happens. */
export function useThreadMessages(
  threadId: string | null,
  filterRef: RefObject<TransactionFilter>,
  listRef: RefObject<HTMLDivElement | null>,
) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [hasMoreOlder, setHasMoreOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  // Set while prepending older messages, so the caller's scroll-to-bottom effect
  // knows to leave the scroll position alone for that update.
  const justLoadedOlderRef = useRef(false);

  // Reset when the thread changes — during render, React's pattern for resetting
  // state on a prop change. Local messages of a just-created thread stay visible
  // until its history loads below, so the first exchange doesn't blink out.
  const [shownThreadId, setShownThreadId] = useState(threadId);
  if (threadId !== shownThreadId) {
    setShownThreadId(threadId);
    setHasMoreOlder(false);
    if (!threadId) setMessages([]);
  }

  useEffect(() => {
    if (!threadId) return;
    getThreadMessages(threadId, { limit: MESSAGE_PAGE_LIMIT }).then(async (res) => {
      const { messages: loaded, exportIndexes } = mapStoredMessages(res.items);
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
  }, [threadId, filterRef]);

  async function loadEarlierMessages() {
    const oldestSeq = messages[0]?.seq;
    if (!threadId || loadingOlder || !hasMoreOlder || oldestSeq === undefined) return;
    setLoadingOlder(true);
    try {
      const res = await getThreadMessages(threadId, { beforeSeq: oldestSeq, limit: MESSAGE_PAGE_LIMIT });
      const container = listRef.current;
      const prevScrollHeight = container?.scrollHeight ?? 0;
      justLoadedOlderRef.current = true;
      setMessages((cur) => [...mapStoredMessages(res.items).messages, ...cur]);
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

  function appendMessage(message: DisplayMessage) {
    setMessages((cur) => [...cur, message]);
  }

  return { messages, appendMessage, hasMoreOlder, loadingOlder, loadEarlierMessages, justLoadedOlderRef };
}
