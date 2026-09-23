import { useQuery } from "@tanstack/react-query";
import { Hash, Paperclip } from "lucide-react";
import { listTransactions } from "../lib/api";
import type { TransactionFilter } from "../lib/api";
import { useTranslation } from "../lib/i18n";
import { receiptViewUrl } from "../lib/receipts";
import IconButton from "./IconButton";

interface Props {
  filter: TransactionFilter;
  onViewImage: (url: string) => void;
  onReferenceTransaction: (id: string) => void;
}

function formatDate(occurredOn: string): string {
  const [year, month, day] = occurredOn.split("-");
  return `${day}.${month}.${year}`;
}

// Grouping-only: the API returns an exact decimal string (integer minor units under
// the hood, see services/transactions/app/money.py) — this never parses it as a
// number, so there's no float rounding risk, just thousands separators inserted into
// the integer part.
function formatAmount(amount: string): string {
  const [intPart, decPart] = amount.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decPart !== undefined ? `${grouped}.${decPart}` : grouped;
}

// Read-only by design — filtering, adding, editing and deleting all happen through
// chat (see ChatPanel and edit_transaction in services/agent/app/tools.py).
export default function TransactionsTable({ filter, onViewImage, onReferenceTransaction }: Props) {
  const { data } = useQuery({
    queryKey: ["transactions", filter],
    queryFn: () => listTransactions(filter),
  });
  const { t, tCategory } = useTranslation();

  return (
    <div className="overflow-x-auto border border-zinc-200 dark:border-zinc-800">
    <table className="w-full min-w-[640px] overflow-hidden text-sm bg-white dark:bg-zinc-900">
      <thead>
        <tr className="bg-zinc-50 dark:bg-zinc-800/60">
          <th className="px-3 py-2 text-start font-medium text-zinc-600 dark:text-zinc-400">{t("colDate")}</th>
          <th className="px-3 py-2 text-start font-medium text-zinc-600 dark:text-zinc-400">{t("colAmount")}</th>
          <th className="px-3 py-2 text-start font-medium text-zinc-600 dark:text-zinc-400">{t("colCurrency")}</th>
          <th className="px-3 py-2 text-start font-medium text-zinc-600 dark:text-zinc-400">{t("colCategory")}</th>
          <th className="px-3 py-2 text-start font-medium text-zinc-600 dark:text-zinc-400">{t("colDescription")}</th>
          <th className="px-3 py-2" />
        </tr>
      </thead>
      <tbody>
        {data && data.items.length === 0 && (
          <tr>
            <td colSpan={6} className="px-3 py-10 text-center text-sm text-zinc-500 dark:text-zinc-400">
              {t("noTransactions")}
            </td>
          </tr>
        )}
        {data?.items.map((tx) => {
          const receiptUrl = receiptViewUrl(tx.receipt_uri);
          return (
            <tr key={tx.id} className="border-t border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/40">
              <td className="px-3 py-3.5 text-zinc-700 dark:text-zinc-300">{formatDate(tx.occurred_on)}</td>
              <td className={tx.type === "expense" ? "px-3 py-3.5 text-red-600 dark:text-red-400" : "px-3 py-3.5 text-emerald-600 dark:text-emerald-400"}>
                {tx.type === "expense" ? "-" : ""}
                {formatAmount(tx.amount)}
              </td>
              <td className="px-3 py-3.5 text-zinc-700 dark:text-zinc-300">{tx.currency}</td>
              <td className="px-3 py-3.5 text-zinc-700 dark:text-zinc-300">{tCategory(tx.category)}</td>
              <td className="px-3 py-3.5 text-zinc-700 dark:text-zinc-300">{tx.description || ""}</td>
              <td className="px-3 py-3.5">
                <div className="flex items-center justify-end gap-1">
                  {receiptUrl && (
                    <IconButton onClick={() => onViewImage(receiptUrl)} label={t("viewReceipt")} align="end">
                      <Paperclip size={14} />
                    </IconButton>
                  )}
                  <IconButton onClick={() => onReferenceTransaction(tx.id)} label={t("referenceInChat")} align="end">
                    <Hash size={14} />
                  </IconButton>
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
  );
}
