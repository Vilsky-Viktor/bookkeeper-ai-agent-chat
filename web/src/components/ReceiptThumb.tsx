import { ZoomIn } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "../lib/i18n";
import { renderPdfFirstPageToDataUrl } from "../lib/pdfThumbnail";

interface Props {
  url: string;
  onView: (url: string) => void;
  onLoad?: () => void;
}

// A receipt attachment can be a PDF (see extract_receipt: PDFs are rendered to an
// image server-side for extraction, but the stored receipt_uri stays the original
// PDF for audit) — <img> can't render that directly, so onError here re-renders its
// first page client-side into the same square instead, same as a photo receipt.
// Only if that itself fails does this fall back to a plain link.
export default function ReceiptThumb({ url, onView, onLoad }: Props) {
  const [pdfThumbUrl, setPdfThumbUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const { t } = useTranslation();

  async function handleImageError() {
    try {
      setPdfThumbUrl(await renderPdfFirstPageToDataUrl(url));
    } catch {
      setFailed(true);
    }
  }

  if (failed) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="inline-block text-xs text-muted-foreground underline hover:text-foreground"
      >
        {t("viewAttachment")}
      </a>
    );
  }

  return (
    <div
      onClick={() => onView(url)}
      className="group relative h-[88px] w-[88px] cursor-pointer overflow-hidden rounded-2xl border border-border"
    >
      <img
        src={pdfThumbUrl ?? url}
        alt="Receipt"
        onError={pdfThumbUrl ? () => setFailed(true) : handleImageError}
        onLoad={onLoad}
        className="block h-full w-full object-cover object-top"
      />
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
        <ZoomIn size={20} className="text-white" />
      </div>
    </div>
  );
}
