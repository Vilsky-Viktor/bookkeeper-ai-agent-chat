import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "../lib/i18n";

interface Props {
  url: string | null;
  onClose: () => void;
}

export default function ReceiptModal({ url, onClose }: Props) {
  const [failed, setFailed] = useState(false);
  // Resetting `failed` when `url` changes during render (React's documented pattern
  // for this) instead of in an effect — avoids the extra render pass an effect-based
  // reset would cause. See https://react.dev/learn/you-might-not-need-an-effect
  const [prevUrl, setPrevUrl] = useState(url);
  if (url !== prevUrl) {
    setPrevUrl(url);
    setFailed(false);
  }
  const { t } = useTranslation();

  useEffect(() => {
    if (!url) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [url, onClose]);

  if (!url) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={onClose}>
      <div
        className="relative max-h-[90vh] max-w-[90vw] rounded-xl bg-white p-3 shadow-xl dark:bg-zinc-900"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute -top-3 -end-3 inline-flex h-7 w-7 items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-600 shadow-sm hover:text-zinc-900 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:text-zinc-100"
        >
          <X size={15} />
        </button>
        {failed ? (
          // A PDF receipt can't render in <img> — offer a direct link instead of a
          // broken-image icon (see ReceiptThumb.tsx for the same fallback in chat).
          <div className="px-6 py-8 text-center text-sm">
            <p className="mb-2.5 text-zinc-500 dark:text-zinc-400">{t("cantPreview")}</p>
            <a href={url} target="_blank" rel="noreferrer" className="text-zinc-900 underline dark:text-zinc-100">
              {t("openInNewTab")}
            </a>
          </div>
        ) : (
          <img
            src={url}
            alt="Receipt"
            onError={() => setFailed(true)}
            className="block max-h-[80vh] max-w-full rounded-lg"
          />
        )}
      </div>
    </div>
  );
}
