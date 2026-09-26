import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createRef } from "react";
import type { ReactNode, RefObject } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TransactionFilter } from "./api";

type SseMessage = { event?: string; data: string };

const { fetchEventSourceMock, fetchAllTransactionsMock } = vi.hoisted(() => ({
  fetchEventSourceMock: vi.fn(),
  fetchAllTransactionsMock: vi.fn(),
}));
vi.mock("@microsoft/fetch-event-source", () => ({ fetchEventSource: fetchEventSourceMock }));
vi.mock("./api", () => ({
  authHeaders: async (h: Record<string, string>) => h,
  fetchAllTransactions: fetchAllTransactionsMock,
}));
vi.mock("./csv", () => ({ createCsvObjectUrl: () => "blob:csv" }));

import { useChatStream } from "./useChatStream";

/** Makes the next send() receive these SSE messages, in order. */
function serverSends(...messages: SseMessage[]) {
  fetchEventSourceMock.mockImplementation(
    async (_url: string, opts: { body: string; onmessage: (m: SseMessage) => void }) => {
      messages.forEach((m) => opts.onmessage(m));
    },
  );
}

const token = (text: string): SseMessage => ({ data: JSON.stringify({ type: "token", text }) });
const event = (name: string, data: object): SseMessage => ({ event: name, data: JSON.stringify(data) });

function setup(threadId: string | null = "thread-1") {
  const callbacks = { onMessage: vi.fn(), onThreadId: vi.fn(), onFilterSet: vi.fn(), onReceiptProposed: vi.fn() };
  const filterRef = createRef<TransactionFilter>() as RefObject<TransactionFilter>;
  filterRef.current = { currency: "USD" };
  const queryClient = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useChatStream(threadId, filterRef, callbacks), { wrapper });
  return { result, callbacks, filterRef, queryClient };
}

describe("useChatStream", () => {
  beforeEach(() => {
    fetchEventSourceMock.mockReset();
    fetchAllTransactionsMock.mockReset().mockResolvedValue([]);
  });

  it("posts the message and appends the user message, then the streamed reply", async () => {
    serverSends(token("Hi"), token(" there"), event("done", { thread_id: "thread-1" }));
    const { result, callbacks } = setup();

    await act(() => result.current.send("hello"));

    const body = JSON.parse(fetchEventSourceMock.mock.calls[0][1].body);
    expect(body).toMatchObject({ thread_id: "thread-1", message: "hello" });
    expect(callbacks.onMessage.mock.calls.map((c) => c[0])).toEqual([
      { role: "user", text: "hello", imageUrl: undefined },
      { role: "assistant", text: "Hi there" },
    ]);
    expect(result.current.streaming).toBe(false);
  });

  it("drops narration streamed before a tool call", async () => {
    serverSends(token("Let me check."), event("reset_pending", {}), token("Done."));
    const { result, callbacks } = setup();

    await act(() => result.current.send("delete it"));

    expect(callbacks.onMessage.mock.calls.at(-1)?.[0].text).toBe("Done.");
  });

  it("reports the new thread's id only when there wasn't one", async () => {
    serverSends(event("done", { thread_id: "new-thread" }));
    const { result, callbacks } = setup(null);

    await act(() => result.current.send("hi"));

    expect(callbacks.onThreadId).toHaveBeenCalledWith("new-thread");
  });

  it("applies a filter at once, so an export in the same turn uses it", async () => {
    serverSends(event("filter_set", { filter: { currency: "EUR" } }), event("export_ready", {}));
    const { result, callbacks, filterRef } = setup();

    await act(() => result.current.send("export my EUR ones"));

    expect(filterRef.current).toEqual({ currency: "EUR" });
    expect(callbacks.onFilterSet).toHaveBeenCalledWith({ currency: "EUR" });
    expect(fetchAllTransactionsMock).toHaveBeenCalledWith({ currency: "EUR" });
    expect(callbacks.onMessage.mock.calls.at(-1)?.[0]).toMatchObject({ csvUrl: "blob:csv" });
  });

  it("treats an empty filter as 'back to the default view', not 'everything'", async () => {
    serverSends(event("filter_set", { filter: {} }));
    const { result, callbacks } = setup();

    await act(() => result.current.send("clear the filter"));

    expect(Object.keys(callbacks.onFilterSet.mock.calls[0][0]).length).toBeGreaterThan(0);
  });

  it("hands a receipt proposal over with each item's proposed category kept", async () => {
    const item = { occurred_on: "2026-01-01", type: "expense", amount: "5", currency: "USD", category: "dining" };
    serverSends(event("receipt_proposed", { items: [item], receipt_uri: "gs://b/r" }));
    const { result, callbacks } = setup();

    await act(() => result.current.send("", "receipts/u1/r.jpg"));

    expect(callbacks.onReceiptProposed.mock.calls[0][0].items[0].suggested_category).toBe("dining");
  });

  it("shows a server error as reply text", async () => {
    serverSends(event("error", { message: "Daily limit reached." }));
    const { result, callbacks } = setup();

    await act(() => result.current.send("hi"));

    expect(callbacks.onMessage.mock.calls.at(-1)?.[0].text).toBe("Daily limit reached.");
  });

  it("refreshes the transactions table when the turn changed it", async () => {
    serverSends(event("table_changed", {}));
    const { result, queryClient } = setup();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await act(() => result.current.send("add a coffee for 5 USD"));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["transactions"] });
  });
});
