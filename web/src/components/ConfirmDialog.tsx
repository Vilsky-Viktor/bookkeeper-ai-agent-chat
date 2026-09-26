import { useEffect } from "react";
import { useTranslation } from "../lib/i18n";

interface Props {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

// A styled stand-in for window.confirm() — same overlay/card shape as ReceiptModal,
// so a destructive action (e.g. deleting a transaction from the table) gets a
// confirmation that actually matches the rest of the app instead of a jarring
// native browser dialog.
export default function ConfirmDialog({ message, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={onCancel}>
      <div
        className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl dark:bg-zinc-900"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="mb-4 text-sm text-zinc-700 dark:text-zinc-300">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:border-zinc-600 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            {t("cancel")}
          </button>
          <button
            onClick={onConfirm}
            className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-700"
          >
            {t("delete")}
          </button>
        </div>
      </div>
    </div>
  );
}
