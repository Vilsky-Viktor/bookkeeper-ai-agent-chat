import { useInfiniteQuery } from "@tanstack/react-query";
import { Hash, Paperclip } from "lucide-react";
import { listTransactions } from "../lib/api";
import type { TransactionFilter } from "../lib/api";
import { useTranslation } from "../lib/i18n";
import { receiptViewUrl } from "../lib/receipts";
import IconButton from "./IconButton";

// How close to the bottom (px) of the table's own scroll container triggers loading
// the next page — matches the 50-row page size on the backend (see
// routers/transactions.py), fetched again each time the user nears the end instead of
// all at once, so a large history doesn't load (or render) in one shot.
const LOAD_MORE_THRESHOLD_PX = 200;

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
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["transactions", filter],
    queryFn: ({ pageParam }: { pageParam: string | undefined }) => listTransactions(filter, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const items = data?.pages.flatMap((p) => p.items);
  const { t, tCategory } = useTranslation();

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    if (
      el.scrollHeight - el.scrollTop - el.clientHeight < LOAD_MORE_THRESHOLD_PX &&
      hasNextPage &&
      !isFetchingNextPage
    ) {
      fetchNextPage();
    }
  }

  return (
    <div onScroll={handleScroll} className="min-h-0 flex-1 overflow-auto">
      <table className="w-full min-w-[640px] border-spacing-0 text-sm bg-white dark:bg-zinc-900">
        <thead className="sticky top-0 z-10 will-change-transform bg-zinc-50 dark:bg-zinc-800">
          <tr>
            <th className="px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">{t("colDate")}</th>
            <th className="px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">{t("colAmount")}</th>
            <th className="px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">{t("colCurrency")}</th>
            <th className="px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">{t("colCategory")}</th>
            <th className="px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">{t("colDescription")}</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {items && items.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-10 text-center text-sm text-zinc-500 dark:text-zinc-400">
                {t("noTransactions")}
              </td>
            </tr>
          )}
          {items?.map((tx) => {
            const receiptUrl = receiptViewUrl(tx.receipt_uri);
            return (
              <tr
                key={tx.id}
                className="border-t border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/40"
              >
                <td className="px-3 py-3.5 text-zinc-700 dark:text-zinc-300">{formatDate(tx.occurred_on)}</td>
                <td
                  className={
                    tx.type === "expense"
                      ? "px-3 py-3.5 text-red-600 dark:text-red-400"
                      : "px-3 py-3.5 text-emerald-600 dark:text-emerald-400"
                  }
                >
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
          {isFetchingNextPage && (
            <tr>
              <td colSpan={6} className="px-3 py-3 text-center text-xs text-zinc-400 dark:text-zinc-600">
                {t("loadingEarlier")}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
