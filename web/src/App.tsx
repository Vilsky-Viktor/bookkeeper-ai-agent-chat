import { useQueryClient } from "@tanstack/react-query";
import type { User } from "firebase/auth";
import { onAuthStateChanged } from "firebase/auth";
import { Coins, LogOut, Moon, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ChatPanel from "./components/ChatPanel";
import type { ChatPanelHandle } from "./components/ChatPanel";
import ReceiptModal from "./components/ReceiptModal";
import TransactionsTable from "./components/TransactionsTable";
import { listThreads } from "./lib/api";
import type { TransactionFilter } from "./lib/api";
import { defaultFilter } from "./lib/filters";
import { auth, signIn, signOut } from "./lib/firebase";
import { LanguageProvider, SUPPORTED_LANGUAGES, useTranslation } from "./lib/i18n";
import { watchSync } from "./lib/sync";
import { useTheme } from "./lib/theme";
import { useMediaQuery } from "./lib/useMediaQuery";
import { useResizable } from "./lib/useResizable";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);

  useEffect(() => onAuthStateChanged(auth, (u) => {
    setUser(u);
    setAuthReady(true);
  }), []);

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
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const chatPanelRef = useRef<ChatPanelHandle>(null);
  const [theme, toggleTheme] = useTheme();
  const queryClient = useQueryClient();
  const { t, language, setLanguage } = useTranslation();

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
    // Threads persist server-side (architecture doc, Chat memory: "chats survive
    // reloads and devices"); on reload the UI just needs to ask for the most recent
    // one instead of starting a fresh, empty thread every time.
    if (!user) return;
    listThreads().then((res) => {
      if (res.items.length > 0) setThreadId(res.items[0].id);
    });
  }, [user]);

  useEffect(() => {
    if (!user) return;
    return watchSync(user.uid, (d, prev) => {
      if (d.transactions_version !== prev.transactions_version) {
        queryClient.invalidateQueries({ queryKey: ["transactions"] });
      }
      if (threadId && d.thread_versions?.[threadId] !== prev.thread_versions?.[threadId]) {
        queryClient.invalidateQueries({ queryKey: ["thread-messages", threadId] });
      }
      if (d.threads_version !== prev.threads_version) {
        queryClient.invalidateQueries({ queryKey: ["threads"] });
      }
    });
  }, [user, threadId, queryClient]);

  useEffect(() => {
    if (!menuOpen) return;
    function onPointerDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [menuOpen]);

  if (!user) {
    return (
      <div className="flex h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <div className="flex flex-col items-center gap-4 rounded-2xl border border-zinc-200 bg-white p-10 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">SMAKER.ai</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{t("signInSubtitle")}</p>
          <button
            onClick={() => signIn()}
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-500 dark:bg-zinc-300 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            {t("signInButton")}
          </button>
        </div>
      </div>
    );
  }

  const avatarLetter = (user.email ?? user.uid).charAt(0).toUpperCase();

  return (
    <div className="flex h-screen flex-col bg-zinc-50 dark:bg-zinc-950">
      <header className="relative z-10 flex items-center justify-between border-b border-zinc-200 bg-white px-4 py-2.5 shadow-[0_4px_6px_-1px_rgb(0_0_0_/_0.05),0_2px_4px_-2px_rgb(0_0_0_/_0.05)] dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex items-center gap-1.5 text-zinc-900 dark:text-zinc-100">
          <Coins size={18} />
          <span className="text-sm font-semibold">SMAKER.ai</span>
        </div>
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((o) => !o)}
            aria-label={user.email ?? user.uid}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-zinc-200 text-xs font-semibold text-zinc-700 transition-colors hover:bg-zinc-300 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
          >
            {avatarLetter}
          </button>
          {menuOpen && (
            <div className="absolute end-0 top-full z-10 mt-2 w-56 rounded-lg border border-zinc-200 bg-white p-1.5 shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
              <div className="truncate px-2.5 py-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                {user.email ?? user.uid}
              </div>
              <div className="px-2.5 py-1.5">
                <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                  {t("language")}
                </label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-sm text-zinc-700 focus:outline-none focus:ring-1 focus:ring-zinc-400/40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
                >
                  {SUPPORTED_LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={() => {
                  toggleTheme();
                  setMenuOpen(false);
                }}
                className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2.5 text-start text-sm text-zinc-700 transition-colors hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
                {theme === "dark" ? t("lightMode") : t("darkMode")}
              </button>
              <button
                onClick={() => signOut()}
                className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2.5 text-start text-sm text-zinc-700 transition-colors hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                <LogOut size={17} />
                {t("signOut")}
              </button>
            </div>
          )}
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div
          className="order-3 flex min-h-0 flex-col bg-white dark:bg-zinc-900 md:order-1"
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
          className="order-2 h-1.5 w-full shrink-0 cursor-row-resize touch-none bg-zinc-200 transition-colors hover:bg-zinc-300 active:bg-zinc-400 dark:bg-zinc-800 dark:hover:bg-zinc-700 dark:active:bg-zinc-600 md:h-full md:w-1.5 md:cursor-col-resize"
        />
        <div className="order-1 min-h-0 min-w-0 flex-1 overflow-auto p-4 md:order-3">
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
