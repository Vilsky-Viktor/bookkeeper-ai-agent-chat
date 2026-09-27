import { formatAmount } from "../lib/format";

// A native <input>'s value can't have mixed font sizes, so showing the decimal part
// smaller than the integer part (to make the currency's actual precision visually
// obvious — see money.py's per-currency exponent, e.g. IDR has none at all) means the
// amount cell isn't a plain always-visible input like every other column: it shows
// this styled, click-to-edit button instead, swapping to a real input only while
// actively being edited.
export default function AmountText({ amount }: { amount: string }) {
  const [intPart, decPart] = formatAmount(amount).split(".");

  return (
    <>
      {intPart}
      {decPart !== undefined && <span className="text-[0.75em] opacity-70">.{decPart}</span>}
    </>
  );
}
