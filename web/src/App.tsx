import type { User } from "firebase/auth";
import { onAuthStateChanged } from "firebase/auth";
import { useEffect, useRef, useState } from "react";
import ChatPanel from "./components/ChatPanel";
import type { ChatPanelHandle } from "./components/ChatPanel";
import GoogleIcon from "./components/GoogleIcon";
import ReceiptModal from "./components/ReceiptModal";
import TransactionsTable from "./components/TransactionsTable";
import { UserMenu } from "./components/UserMenu";
import { Wordmark } from "./components/Wordmark";
import { Button } from "./components/ui/button";
import { listThreads } from "./lib/api";
import type { TransactionFilter } from "./types/api";
import { defaultFilter } from "./lib/filters";
import { auth, signIn } from "./lib/firebase";
import { LanguageProvider, useTranslation } from "./lib/i18n";
import { useMediaQuery } from "./lib/useMediaQuery";
import { useResizable } from "./lib/useResizable";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);

  useEffect(
    () =>
      onAuthStateChanged(auth, (u) => {
        setUser(u);
        setAuthReady(true);
      }),
    [],
  );

  if (!authReady) return null;

  return (
    <LanguageProvider userId={user?.uid ?? null}>
      <AppContent user={user} />
    </LanguageProvider>
  );
}

function AppContent({ user }: { user: User | null }) {
  const [filter, setFilter] = useState<TransactionFilter>(defaultFilter());
  const [threadId, setThreadId] = useState<string | null>(null);
  const [viewingImage, setViewingImage] = useState<string | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle>(null);
  const { t } = useTranslation();

  // Desktop: a vertical handle resizes the chat pane's width (left/right split).
  // Mobile: a horizontal handle resizes its height instead (top/bottom split, table
  // on top, chat on bottom — see the order-* classes below). Same hook, different
  // axis/bounds/storage key per layout.
  const isDesktop = useMediaQuery("(min-width: 768px)");
  const { size: chatSize, handleProps: chatHandleProps } = useResizable(
    isDesktop
      ? { axis: "x", initial: 480, min: 320, max: 800, storageKey: "chatPaneWidth" }
      : { axis: "y", initial: 280, min: 140, max: 640, storageKey: "chatPaneHeight", reverse: true },
  );

  useEffect(() => {
    // Threads persist server-side (they survive reloads and devices), so on reload
    // ask for the most recent one instead of starting a fresh, empty thread.
    if (!user) return;
    listThreads().then((res) => {
      if (res.items.length > 0) setThreadId(res.items[0].id);
    });
  }, [user]);

  if (!user) {
    return (
      <div className="flex h-screen items-center justify-center bg-background p-4">
        <div className="flex flex-col items-center gap-6 text-center">
          <Wordmark className="text-6xl" />
          <p className="max-w-xs text-base text-muted-foreground">{t("signInSubtitle")}</p>
          <Button variant="outline" size="lg" className="h-10 px-5" onClick={() => signIn()}>
            <GoogleIcon size={16} />
            {t("signInButton")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="relative z-30 h-14 shrink-0 border-b">
        <div className="flex h-full items-center justify-between gap-4 px-4 sm:px-6">
          <Wordmark className="text-xl leading-none" />
          <UserMenu user={user} />
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col p-3 md:flex-row md:p-4">
        <div
          className="order-3 flex min-h-0 flex-col gap-3 md:order-1"
          style={isDesktop ? { width: chatSize } : { height: chatSize }}
        >
          <ChatPanel
            ref={chatPanelRef}
            threadId={threadId}
            onThreadId={setThreadId}
            filter={filter}
            onFilterSet={setFilter}
            onViewImage={setViewingImage}
          />
        </div>
        <div
          {...chatHandleProps}
          role="separator"
          aria-orientation={isDesktop ? "vertical" : "horizontal"}
          className="order-2 my-1.5 h-1 w-12 shrink-0 cursor-row-resize touch-none self-center rounded-full bg-border transition-colors hover:bg-ring/50 active:bg-ring md:mx-1.5 md:my-0 md:h-12 md:w-1 md:cursor-col-resize"
        />
        <div className="order-1 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-3xl bg-card shadow-sm ring-1 ring-foreground/5 md:order-3">
          <TransactionsTable
            filter={filter}
            onViewImage={setViewingImage}
            onReferenceTransaction={(id) => chatPanelRef.current?.insertReference(id)}
          />
        </div>
      </div>
      <ReceiptModal url={viewingImage} onClose={() => setViewingImage(null)} />
    </div>
  );
}
