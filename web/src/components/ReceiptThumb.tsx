import { useState } from "react";
import { useTranslation } from "../lib/i18n";

interface Props {
  url: string;
  onView: (url: string) => void;
  onLoad?: () => void;
}

// A receipt attachment can be a PDF (see extract_receipt: PDFs are rendered to an
// image server-side for extraction, but the stored receipt_uri stays the original
// PDF for audit). <img> can't render that, so fall back to a plain link instead of a
// broken-image icon.
export default function ReceiptThumb({ url, onView, onLoad }: Props) {
  const [failed, setFailed] = useState(false);
  const { t } = useTranslation();

  if (failed) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="inline-block text-xs text-zinc-500 underline hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
      >
        {t("viewAttachment")}
      </a>
    );
  }

  return (
    <img
      src={url}
      alt="Receipt"
      onClick={() => onView(url)}
      onError={() => setFailed(true)}
      onLoad={onLoad}
      className="block max-h-[140px] max-w-[140px] cursor-pointer rounded-lg border border-zinc-200 object-cover dark:border-zinc-700"
    />
  );
}
