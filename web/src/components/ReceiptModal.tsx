import { useState } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useTranslation } from "@/lib/i18n";

interface Props {
  url: string | null;
  onClose: () => void;
}

/** A receipt shown full size, in the prepza project's dialog. */
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

  return (
    <Dialog open={url !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-auto max-w-[90vw] gap-0 p-3 sm:max-w-[90vw]">
        {url &&
          (failed ? (
            // A PDF receipt can't render in <img> — offer a direct link instead of a
            // broken-image icon (see ReceiptThumb.tsx for the same fallback in chat).
            <div className="px-6 py-8 text-center text-sm">
              <p className="mb-2.5 text-muted-foreground">{t("cantPreview")}</p>
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline-offset-4 hover:underline"
              >
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
          ))}
      </DialogContent>
    </Dialog>
  );
}
