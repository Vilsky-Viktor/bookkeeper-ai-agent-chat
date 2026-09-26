"""The receipt-extraction vision prompt — like context/prompts.py's SYSTEM_PROMPT,
heavily iterated across real bug-fix rounds; most clauses here exist because of a
specific observed extraction failure (locale-formatted amounts, fees folded into a
product's price, discounts reported as their own line item), not speculative
hardening. Read a clause's neighboring sentence before trimming it."""

RECEIPT_EXTRACTION_PROMPT = """First decide whether this image/document is actually a \
purchase receipt, invoice, or similar proof-of-purchase listing items and prices — \
not an unrelated photo, screenshot, or document.

If it is NOT a receipt, reply with JSON only, no prose:
{"is_receipt": false}

If it IS a receipt, extract every line item and reply with JSON only, no prose, in \
exactly this shape:
{"is_receipt": true, "merchant": "string", "occurred_on": "YYYY-MM-DD",
 "currency": "3-letter ISO 4217 code", "items": [{"description": "string", "amount": "12.50"}]}
Use your best guess for any field you can't read exactly, EXCEPT merchant: if the \
merchant/store name genuinely isn't identifiable anywhere on the receipt, set \
"merchant" to null — never write a placeholder like "Unknown"/"N/A"/"store" as if it \
were the real name, since that gets folded straight into the item description and \
ends up looking like a real (wrong) merchant name (e.g. "3x Camel White 20 - \
Unknown"). It's fine, normal, and preferred for an item's description to just name \
the item with no merchant at all when there isn't one to read. Today's date is {today}. \
For occurred_on: if the receipt prints an actual calendar date, use that exact date, \
converted to YYYY-MM-DD — prefer the receipt's own date over today's whenever the \
receipt shows one, even if that date is recent. Some receipts (e.g. from an app or \
POS system) print a relative label instead of a calendar date, like "Today, 5:52 PM" \
or "Yesterday" — resolve that against today's date above ("Today" -> {today} itself, \
"Yesterday" -> the day before), don't leave it as-is or guess an unrelated date. If \
the date is genuinely illegible or missing entirely, use today's date as the fallback. \
Receipts are almost always from very recently, so if a printed calendar date is \
partly unclear, prefer a reading close to today over one far in the past or future, \
and double-check the year in particular: a misread single digit there (e.g. "23" for \
"26") is a far bigger error than the same mistake in the day or month. \
amount is a clean canonical \
decimal string: "." as the real decimal point ONLY, matching the currency's actual \
precision (2 decimals for most currencies, e.g. "12.50"; a plain integer with no "." \
at all for a zero-decimal currency like IDR/JPY/KRW/VND, e.g. "104700"; 3 decimals \
for a currency like BHD/KWD, e.g. "1.234") — NEVER a thousands separator of any kind \
("," "." or a space between digit groups). Many receipts print larger amounts with a \
thousands separator (e.g. "1.234.567" or "1,234,567" or "1 234 567" might all appear \
on real receipts depending on locale, especially for zero-decimal currencies like IDR \
where every ordinary amount is already in the thousands) — recognize that grouping \
from context (the currency, the typical size of a purchase, the receipt's own \
subtotal/total math) and strip it, writing the true numeric amount with correct \
precision instead of copying the receipt's punctuation verbatim; e.g. a receipt \
showing "104.700" for an IDR item means one hundred four thousand seven hundred \
rupiah, written here as "104700", not "104.70". Some receipts list item names and \
quantities but NOT an individual price per line — e.g. an app/delivery order receipt \
that says the price is shown in the app, or a printed total with no per-item price \
column at all. NEVER invent a per-item amount in that case (in particular, never use \
a quantity number as if it were a price — a quantity like "3" is not an amount). \
Instead, when individual prices aren't printed, collapse everything into ONE item: \
set "amount" to the receipt's actual total — what was actually paid, i.e. after any \
discount, matching its final "total"/"payment"/"paid" line, not a pre-discount \
subtotal — and set "description" to a short list of what was purchased (e.g. "3x \
Camel White 20, FAMRT ECO PB"). Only split into multiple items when the receipt \
itself prints a distinct price next to each one. The sum of every item's "amount" \
must always equal what was actually paid — the receipt's final "total \
payment"/"total paid" line, not just the sum of product prices — but a fee is never \
folded into a product's own amount, not even when there's only one product: if the \
receipt adds a charge on top of the item prices (delivery fee, packaging fee, \
service fee, tip, tax, etc.) to reach that final total, ALWAYS give it its own \
separate item, e.g. {"description": "Delivery & packaging fee", "amount": "..."}, \
never mixed into a product's price — a fee and a purchased item are categorically \
different (a delivery charge isn't part of what the cigarettes/dishes/groceries \
themselves cost) and merging them corrupts both the amount and the category for \
whatever the fee gets folded into. This applies the same way whether it's one \
product plus a delivery/packaging fee or a restaurant bill with many dishes plus a \
shared service charge/tax/tip: the charge is always its own item, on its own, never \
split across or folded into the product(s) it was charged alongside. Such a charge \
is sometimes printed only as a percentage (e.g. "+15% service") without its own \
computed amount — when that's the case, calculate the actual amount yourself (that \
percentage of the subtotal it applies to, as shown by the receipt's own total math) \
rather than skipping it for lacking a printed number. The opposite also happens, \
mostly on e-commerce/marketplace checkout receipts and food-delivery apps (GoFood/ \
GrabFood/ShopeeFood-style "Price / delivery fee / Other discounts / Total payment" \
breakdowns are a very common example): a discount, voucher, or promo deduction \
printed as its own negative-amount line (e.g. "Shipping Discount", "Voucher \
Applied", "Promo", "Other discounts"). Never report one of these as its own item — \
it isn't a purchase, it's a reduction of what something else cost, and this system \
has no way to store a negative amount at all (every item's amount must be a real \
positive number; there is no such thing as a negative-amount item here, not even for \
a refund). Net it against the specific charge it reduces instead: if a fee and a \
same-amount discount for that fee cancel out (e.g. a "Shipping Fee" fully offset by \
a "Shipping Discount"), the net cost of that fee is zero, so omit it entirely rather \
than reporting a fee that ultimately cost nothing; otherwise — including a generic, \
not-fee-specific discount line like "Other discounts" or "Order discount" — subtract \
it from the product/merchandise item(s)' amount instead, never from a fee. E.g. \
"Price 63.800" + "Handling and delivery fee 26.900" + "Other discounts -6.000" = \
"Total payment 84.700" becomes exactly two items: the product at 57800 (63800 minus \
the 6000 discount) and the delivery fee at 26900 untouched — never a third item for \
the discount itself. Every item you report must have a real positive cost. Never \
report only the product \
subtotal when the receipt shows a higher amount was actually paid, and never report \
only the total-including-fees as if it were a single product's price. Write "merchant" \
and every item's "description" \
in {language} — if the receipt itself is in a different language, translate that text \
into {language}; only the merchant/item text is translated, the currency code, amount \
and date stay exactly as read."""
