"""The categorizer's prompt (services/categorize.py): the category definitions, how to use
the user's past corrections. The reply's shape is a structured output schema."""

# Short definitions so an ambiguous item (e.g. toothpaste from a minimarket that also
# sells food) lands on the right bucket instead of the merchant's usual one. "income"
# has none: it's never guessed, only set for income transactions.
CATEGORY_DEFINITIONS = {
    "groceries": "raw/packaged food and household consumables bought to prepare or stock at home (rice, produce, snacks, cooking oil, cleaning supplies) — food and consumables ONLY: tobacco and alcohol bought from a grocery store or minimarket are not food, so they belong in shopping instead, not groceries just because of where they were bought",
    "dining": "prepared food and drink consumed out or ordered in (restaurants, cafes, takeout, delivery)",
    "transport": "getting from place to place (fuel, rideshare, public transit, parking, tolls)",
    "housing": "rent, mortgage, home repairs and furnishings",
    "utilities": "recurring service bills (electricity, water, gas, internet, phone plan)",
    "entertainment": "one-off leisure and media purchases (movie tickets, games, hobbies, events)",
    "health": "pharmacy, medical care, and personal care/hygiene items (toothpaste, soap, medicine, doctor visits)",
    "shopping": "clothing, electronics, tobacco, alcohol, and other general retail goods not covered above",
    "travel": "flights, hotels, and trip-specific costs",
    "subscriptions": "recurring or prepaid plans for software, digital and membership services (streaming, apps, AI tools, cloud storage, gyms), including usage top-ups on those plans — but home service bills (electricity, water, internet, phone plan) are utilities",
    "fees": "bank fees, service charges, interest, penalties",
    "other": "anything that genuinely doesn't fit the categories above",
}


MATCHING_RULES = (
    "If a description clearly describes the same purchase as one of those "
    "corrections — even worded differently, abbreviated, or naming the merchant/place "
    'slightly differently (e.g. "coffee at Starbucks" and "Starbucks latte" are the '
    'same kind of purchase; "claude subscription" and "Claude AI subscription '
    "payment\" are the same purchase) — use that correction's category, even if it's "
    "a custom one not in the list above. Otherwise classify based on what the item "
    "itself is — the same place can sell items across several categories in one "
    "purchase (e.g. a minimarket receipt where rice is groceries but toothpaste from "
    "the same receipt is health, not groceries), so don't assume every item from a "
    "given place shares one category."
)


CATEGORIZE_PROMPT = """Classify each of these line items into exactly one of these categories:
{category_list}

Items:
{items}

The user has previously corrected these categorizations:
{history}

{matching_rules} Give exactly one category per item, in the same order as the items."""
