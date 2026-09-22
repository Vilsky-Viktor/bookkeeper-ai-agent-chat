import { doc, onSnapshot } from "firebase/firestore";
import { CLIENT_ID, db } from "./firebase";

export interface SyncDoc {
  transactions_version?: number;
  thread_versions?: Record<string, number>;
  threads_version?: number;
  origin?: string;
  updated_at?: unknown;
}

export function watchSync(uid: string, onChange: (d: SyncDoc, prev: SyncDoc) => void) {
  let prev: SyncDoc | null = null;
  return onSnapshot(doc(db, "sync", uid), (snap) => {
    const d = (snap.data() as SyncDoc) ?? {};
    if (prev && d.origin !== CLIENT_ID) onChange(d, prev);
    prev = d;
  });
}
