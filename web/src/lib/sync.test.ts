import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SyncDoc } from "./sync";

// vi.mock factories are hoisted above regular imports, so anything they close over
// has to come from vi.hoisted() — a plain module-scope const wouldn't be initialized
// yet when the factory actually runs.
const { docMock, onSnapshotMock, fireSnapshot } = vi.hoisted(() => {
  let onNext: ((snap: { data: () => SyncDoc | undefined }) => void) | undefined;
  const onSnapshotMock = vi.fn((_ref: unknown, callback: typeof onNext) => {
    onNext = callback;
    return vi.fn(); // unsubscribe
  });
  const docMock = vi.fn((_db: unknown, collection: string, uid: string) => ({ collection, uid }));
  function fireSnapshot(data: SyncDoc | undefined) {
    onNext?.({ data: () => data });
  }
  return { docMock, onSnapshotMock, fireSnapshot };
});

vi.mock("./firebase", () => ({ db: {}, CLIENT_ID: "local-client" }));
vi.mock("firebase/firestore", () => ({ doc: docMock, onSnapshot: onSnapshotMock }));

const { watchSync } = await import("./sync");

describe("watchSync", () => {
  beforeEach(() => {
    docMock.mockClear();
    onSnapshotMock.mockClear();
  });

  it("subscribes to the sync/<uid> doc", () => {
    watchSync("uid-1", vi.fn());
    expect(docMock).toHaveBeenCalledWith({}, "sync", "uid-1");
  });

  it("does not call onChange on the first snapshot — there's no prior state to diff against", () => {
    const onChange = vi.fn();
    watchSync("uid-1", onChange);
    fireSnapshot({ transactions_version: 1, origin: "other-client" } satisfies SyncDoc);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("calls onChange with (new, previous) when a later snapshot originates elsewhere", () => {
    const onChange = vi.fn();
    watchSync("uid-1", onChange);
    const first: SyncDoc = { transactions_version: 1, origin: "other-client" };
    const second: SyncDoc = { transactions_version: 2, origin: "other-client" };
    fireSnapshot(first);
    fireSnapshot(second);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(second, first);
  });

  it("does not call onChange when the update originated from this same client", () => {
    const onChange = vi.fn();
    watchSync("uid-1", onChange);
    fireSnapshot({ transactions_version: 1, origin: "local-client" });
    fireSnapshot({ transactions_version: 2, origin: "local-client" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("treats a missing doc as an empty object", () => {
    const onChange = vi.fn();
    watchSync("uid-1", onChange);
    fireSnapshot(undefined);
    const second: SyncDoc = { transactions_version: 1, origin: "other-client" };
    fireSnapshot(second);
    expect(onChange).toHaveBeenCalledWith(second, {});
  });
});
