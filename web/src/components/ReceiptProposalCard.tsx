import type { ProposedItem, ReceiptProposal } from "../lib/chat";
import { BUILT_IN_CATEGORIES, useTranslation } from "../lib/i18n";

const inputClass =
  "rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs text-zinc-900 focus:outline-none focus:ring-2 focus:ring-sky-500/40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:focus:ring-sky-400/40";

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
    <div className="rounded-xl border border-dashed border-zinc-300 bg-zinc-100 p-3 dark:border-zinc-700 dark:bg-zinc-800/80">
      <strong className="mb-2.5 block text-sm font-medium text-zinc-900 dark:text-zinc-100">
        {t("receiptFoundHeading")}
      </strong>
      {proposal.items.map((item, i) => (
        <div className="flex flex-col gap-1.5 py-1 text-sm" key={i}>
          <input
            value={item.description ?? ""}
            onChange={(e) => onChange(i, "description", e.target.value)}
            className={`${inputClass} w-full`}
          />
          <div className="flex items-center gap-1.5">
            <select
              value={item.category}
              onChange={(e) => onChange(i, "category", e.target.value)}
              className={`${inputClass} min-w-0 flex-1`}
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
            <input
              value={item.amount}
              onChange={(e) => onChange(i, "amount", e.target.value)}
              className={`${inputClass} w-28`}
            />
            <input
              value={item.currency}
              onChange={(e) => onChange(i, "currency", e.target.value.toUpperCase())}
              className={`${inputClass} w-16`}
            />
          </div>
        </div>
      ))}
      <div className="mt-2 flex gap-2">
        <button
          onClick={onConfirm}
          className="rounded-lg bg-sky-200 px-3 py-1.5 text-xs font-medium text-sky-900 transition-colors hover:bg-sky-300 dark:bg-sky-900/70 dark:text-sky-100 dark:hover:bg-sky-900/90"
        >
          {t("confirmAndSave")}
        </button>
        <button
          onClick={onCancel}
          className="rounded-lg border border-sky-600 px-3 py-1.5 text-xs font-medium text-sky-600 transition-colors hover:bg-sky-50 dark:border-sky-400 dark:text-sky-400 dark:hover:bg-sky-950/40"
        >
          {t("cancel")}
        </button>
      </div>
    </div>
  );
}
