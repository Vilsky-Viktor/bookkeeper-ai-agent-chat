import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Hash, Paperclip, Trash2 } from "lucide-react";
import { useState } from "react";
import { deleteTransaction, listTransactions, patchTransaction } from "../lib/api";
import type { Transaction, TransactionFilter } from "../lib/api";
import { BUILT_IN_CATEGORIES, useTranslation } from "../lib/i18n";
import { receiptViewUrl } from "../lib/receipts";
import ConfirmDialog from "./ConfirmDialog";
import IconButton from "./IconButton";
import Tooltip from "./Tooltip";

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

// Grouping-only: the API returns an exact decimal string (integer minor units under
// the hood, see services/transactions/app/money.py) — this never parses it as a
// number, so there's no float rounding risk, just thousands separators inserted into
// the integer part.
function formatAmount(amount: string): string {
  const [intPart, decPart] = amount.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decPart !== undefined ? `${grouped}.${decPart}` : grouped;
}

const editableCellClass =
  "w-full min-w-0 rounded-md border border-transparent bg-transparent px-1.5 py-1 text-inherit focus:border-zinc-300 focus:bg-white focus:outline-none focus:ring-1 focus:ring-sky-500/40 dark:focus:border-zinc-600 dark:focus:bg-zinc-800";

// Every field is directly editable in place (a plain uncontrolled input per cell,
// keyed on the row's current value so it remounts — and picks up the fresh
// server value — after a successful edit elsewhere invalidates the query, or
// resets itself back if this edit's own PATCH fails); category is a dropdown built
// from the same built-in list the backend categorizer and the receipt-proposal
// card use (see ChatPanel's BUILT_IN_CATEGORIES usage), date is a native date input.
// table-fixed + the <colgroup> below give each column a predictable width instead of
// letting content dictate it — otherwise a header label like "Currency" stretches
// its column far past what a 3-letter value needs.
export default function TransactionsTable({ filter, onViewImage, onReferenceTransaction }: Props) {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["transactions", filter],
    queryFn: ({ pageParam }: { pageParam: string | undefined }) => listTransactions(filter, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const items = data?.pages.flatMap((p) => p.items);
  const { t, tCategory } = useTranslation();
  const queryClient = useQueryClient();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

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

  async function handlePatch(tx: Transaction, field: keyof Transaction, value: string) {
    if (value === tx[field]) return; // no-op edit (e.g. blurred without changing anything)
    try {
      await patchTransaction(tx.id, { [field]: value }, crypto.randomUUID());
    } catch (e) {
      console.error(`failed to update transaction ${tx.id}.${field}`, e);
    } finally {
      // Always resync, success or failure — on failure this reverts the cell back to
      // the real (unchanged) server value instead of leaving the attempted edit
      // displayed as if it had actually saved.
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    }
  }

  async function performDelete(id: string) {
    setConfirmDeleteId(null);
    try {
      await deleteTransaction(id, crypto.randomUUID());
    } catch (e) {
      console.error(`failed to delete transaction ${id}`, e);
    } finally {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    }
  }

  return (
    <div onScroll={handleScroll} className="min-h-0 flex-1 overflow-auto">
      <table className="w-full min-w-[640px] table-fixed border-spacing-0 text-sm bg-white dark:bg-zinc-900">
        <colgroup>
          <col className="w-[130px]" />
          <col className="w-[110px]" />
          <col className="w-24" />
          <col className="w-[140px]" />
          <col />
          <col className="w-28" />
        </colgroup>
        <thead className="sticky top-0 z-10 will-change-transform bg-zinc-50 dark:bg-zinc-800">
          <tr>
            <th className="truncate px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">
              {t("colDate")}
            </th>
            <th className="truncate px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">
              {t("colAmount")}
            </th>
            <th className="truncate px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">
              {t("colCurrency")}
            </th>
            <th className="truncate px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">
              {t("colCategory")}
            </th>
            <th className="truncate px-3 py-2 text-start font-normal text-zinc-600 dark:text-zinc-400">
              {t("colDescription")}
            </th>
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
            const amountColor =
              tx.type === "expense" ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400";
            const descriptionInput = (
              <input
                key={`description-${tx.id}-${tx.description}`}
                defaultValue={tx.description ?? ""}
                onBlur={(e) => handlePatch(tx, "description", e.target.value)}
                className={`${editableCellClass} truncate`}
              />
            );
            return (
              <tr
                key={tx.id}
                className="border-t border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/40"
              >
                <td className="px-1 py-1 text-zinc-700 dark:text-zinc-300">
                  <input
                    key={`date-${tx.id}-${tx.occurred_on}`}
                    type="date"
                    defaultValue={tx.occurred_on}
                    onChange={(e) => e.target.value && handlePatch(tx, "occurred_on", e.target.value)}
                    // The native calendar-icon glyph follows color-scheme, not text
                    // color — without this it renders as a fixed dark icon that's
                    // invisible against a dark input background.
                    className={`${editableCellClass} [color-scheme:light] dark:[color-scheme:dark]`}
                  />
                </td>
                <td className={`px-1 py-1 ${amountColor}`}>
                  <div className="flex items-center gap-0.5">
                    <span aria-hidden="true">{tx.type === "expense" ? "-" : ""}</span>
                    <input
                      key={`amount-${tx.id}-${tx.amount}`}
                      defaultValue={formatAmount(tx.amount)}
                      onBlur={(e) => handlePatch(tx, "amount", e.target.value.replaceAll(",", "").trim())}
                      className={editableCellClass}
                    />
                  </div>
                </td>
                <td className="px-1 py-1 text-zinc-700 dark:text-zinc-300">
                  <input
                    key={`currency-${tx.id}-${tx.currency}`}
                    defaultValue={tx.currency}
                    maxLength={3}
                    onBlur={(e) => handlePatch(tx, "currency", e.target.value.trim().toUpperCase())}
                    className={`${editableCellClass} uppercase`}
                  />
                </td>
                <td className="px-1 py-1 text-zinc-700 dark:text-zinc-300">
                  <select
                    key={`category-${tx.id}-${tx.category}`}
                    defaultValue={tx.category}
                    onChange={(e) => handlePatch(tx, "category", e.target.value)}
                    className={editableCellClass}
                  >
                    {!BUILT_IN_CATEGORIES.includes(tx.category.toLowerCase()) && (
                      <option value={tx.category}>{tCategory(tx.category)}</option>
                    )}
                    {BUILT_IN_CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {tCategory(c)}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-1 py-1 text-zinc-700 dark:text-zinc-300">
                  {tx.description ? (
                    <Tooltip label={tx.description} className="w-full">
                      {descriptionInput}
                    </Tooltip>
                  ) : (
                    descriptionInput
                  )}
                </td>
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
                    <IconButton onClick={() => setConfirmDeleteId(tx.id)} label={t("deleteTransaction")} align="end">
                      <Trash2 size={14} />
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
      {confirmDeleteId && (
        <ConfirmDialog
          message={t("confirmDeleteTransaction")}
          onConfirm={() => performDelete(confirmDeleteId)}
          onCancel={() => setConfirmDeleteId(null)}
        />
      )}
    </div>
  );
}
