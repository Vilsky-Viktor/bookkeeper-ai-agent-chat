import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { useTranslation } from "@/lib/i18n";

interface Props {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/** A confirmation for a destructive action (deleting a transaction from the table), on the
 * prepza project's dialog instead of the browser's window.confirm(). */
export default function ConfirmDialog({ message, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent showCloseButton={false}>
        <DialogDescription>{message}</DialogDescription>
        <DialogFooter>
          <Button variant="outline" className="h-10 px-5 text-base" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button variant="destructive" className="h-10 px-5 text-base" onClick={onConfirm}>
            {t("delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
