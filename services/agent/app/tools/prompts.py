"""The receipt-extraction vision prompt. A receipt becomes ONE transaction for its
total — per-item price extraction (quantities, per-line discounts, fees netted into
products) was dropped as too unreliable. Item names are still read, without prices,
only so receipts.py can pick the receipt's category by majority. Examples are
deliberately locale-neutral: receipts come from any country in any language."""

RECEIPT_EXTRACTION_PROMPT = """You read a photo (or PDF render) of a receipt. Receipts \
can come from any country and be printed in any language; recognize each kind of line \
by what it does, not by specific wording. Reply with JSON only: no prose, no markdown \
fences.

If this is not a purchase receipt, invoice, or similar proof of purchase (e.g. an \
unrelated photo, screenshot, or document), reply exactly:
{"is_receipt": false}

If it is, reply in exactly this shape:
{"is_receipt": true, "merchant": "string or null", "occurred_on": "YYYY-MM-DD", \
"currency": "3-letter ISO 4217 code", "total_paid": "12.50", \
"description": "string", "items": ["string", "string"]}

FIELDS
- total_paid: the final amount actually paid for the whole purchase, i.e. the \
receipt's grand total after all discounts, fees, tips and taxes. It is NOT the \
subtotal, NOT the amount of cash or card tendered, and NOT the change given back.
- merchant: the store/merchant name as printed. If it genuinely isn't identifiable \
anywhere on the receipt, set "merchant" to null. Never write a placeholder like \
"Unknown", "N/A" or "store".
- occurred_on: today's date is {today}.
  - If the receipt prints a calendar date, use that exact date converted to \
YYYY-MM-DD, reading it in the receipt's local date order (day/month vs month/day).
  - If it prints a relative label instead, like "Today, 5:52 PM" or "Yesterday", \
resolve it against today's date ("Today" -> {today}, "Yesterday" -> the day before).
  - If the date is illegible or missing, use {today}.
  - Receipts are almost always recent. If a printed date is partly unclear, prefer a \
reading close to today, and double-check the year in particular.
- currency: the ISO 4217 code for the receipt's currency. When no code is printed, \
infer it from the currency symbol together with the store's country.
- description: a short summary of what was bought, at most about 60 characters, \
naming the main items rather than listing everything, e.g. "Orange juice, shampoo \
and 3 more items". When the receipt doesn't name the products, describe the kind of \
purchase from context instead (the merchant, icons, layout), e.g. "Restaurant \
delivery order", "Fuel", "Pharmacy purchase" — never a vague "Food and delivery" or \
"Purchase". Don't include the merchant; it's added later.
- items: the name of every product actually bought, one string each, in receipt \
order, without prices or quantities (e.g. ["Nasi goreng", "Iced tea", "Shampoo \
400ml"]). These are used to decide the receipt's category, so list ONLY real \
products: never fees (delivery, service, packaging), tips, taxes, discounts, \
vouchers, payment or change lines, and never summary labels like "Price", \
"Subtotal" or "Total". If the receipt doesn't name any products, reply with an \
empty list: [].
- Language: write "merchant", "description" and every entry in "items" in \
{language}, translating if the receipt is in another language. The currency code, \
amount and date stay exactly as read.

AMOUNT FORMAT (total_paid)
- A plain decimal string, with "." as the real decimal point only, at the currency's \
precision: 2 decimals for most currencies ("12.50"); no "." at all for zero-decimal \
currencies such as JPY, KRW, VND, IDR ("104700"); 3 decimals for BHD/KWD ("1.234").
- Never include a thousands separator. Depending on locale, receipts group digits as \
"1.234.567", "1,234,567", "1 234 567" or "1'234'567", and use "," or "." as the \
decimal mark. Work out which punctuation is grouping from the currency and typical \
price levels, then write the true amount: "104.700" in a zero-decimal currency is \
one hundred four thousand seven hundred, so write "104700", not "104.70"; \
"1.234,50" on a euro receipt is "1234.50"."""
