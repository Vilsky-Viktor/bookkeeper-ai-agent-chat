import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BUILT_IN_CATEGORIES, useTranslation } from "@/lib/i18n";
import type { ProposedItem, ReceiptProposal } from "@/types/chat";

// The native category <select>, styled as the prepza project's Input.
const selectClass =
  "h-8 min-w-0 flex-1 rounded-full border border-input bg-muted px-3 text-sm transition-colors outline-none focus-visible:border-ring dark:bg-input/30";

interface Props {
  proposal: ReceiptProposal;
  onChange: (index: number, field: keyof ProposedItem, value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

/** The editable transaction proposed from a receipt; nothing is saved until Confirm. */
export default function ReceiptProposalCard({ proposal, onChange, onConfirm, onCancel }: Props) {
  const { t, tCategory } = useTranslation();

  return (
    <div className="space-y-3 rounded-2xl border bg-background/40 p-4">
      <h3 className="font-heading text-sm font-medium">{t("receiptFoundHeading")}</h3>
      {proposal.items.map((item, i) => (
        <div className="flex flex-col gap-2" key={i}>
          <Input
            value={item.description ?? ""}
            onChange={(e) => onChange(i, "description", e.target.value)}
            aria-label={t("colDescription")}
          />
          <div className="flex items-center gap-2">
            <select
              value={item.category}
              onChange={(e) => onChange(i, "category", e.target.value)}
              aria-label={t("colCategory")}
              className={selectClass}
            >
              {!BUILT_IN_CATEGORIES.includes(item.category.toLowerCase()) && (
                <option value={item.category}>{tCategory(item.category)}</option>
              )}
              {BUILT_IN_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {tCategory(c)}
                </option>
              ))}
            </select>
            <Input
              value={item.amount}
              onChange={(e) => onChange(i, "amount", e.target.value)}
              aria-label={t("colAmount")}
              className="w-28"
            />
            <Input
              value={item.currency}
              onChange={(e) => onChange(i, "currency", e.target.value.toUpperCase())}
              aria-label={t("colCurrency")}
              className="w-20"
            />
          </div>
        </div>
      ))}
      <div className="flex gap-2 pt-1">
        <Button onClick={onConfirm}>{t("confirmAndSave")}</Button>
        <Button variant="outline" onClick={onCancel}>
          {t("cancel")}
        </Button>
      </div>
    </div>
  );
}
