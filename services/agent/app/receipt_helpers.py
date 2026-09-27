"""Pure helpers for a read receipt: merchant folding and the majority category."""

from collections import Counter

UNKNOWN_MERCHANT_PLACEHOLDERS = {"unknown", "n/a", "na", "none", "store", "merchant", "-"}


def fold_merchant(description: str | None, merchant: str | None) -> str | None:
    """There's no merchant field downstream — the vision model still extracts it
    separately (helps it parse the receipt correctly), but it gets folded into the
    line item's description here rather than sent on its own. The prompt tells the
    model to return null rather than a placeholder when it can't read a merchant
    name, but this is a defensive backstop in case it still slips one through — a
    literal "Unknown" folded in looks like a real (wrong) merchant name."""
    description = (description or "").strip()
    merchant = (merchant or "").strip()

    if merchant.lower() in UNKNOWN_MERCHANT_PLACEHOLDERS:
        merchant = ""

    if not merchant:
        return description or None

    if not description:
        return merchant

    if merchant.lower() in description.lower():
        return description

    return f"{description} - {merchant}"


def majority_category(categories: list[str]) -> str:
    """Most common category across the receipt's items; a tie goes to whichever of
    the tied categories appears first on the receipt."""

    if not categories:
        return "other"
    counts = Counter(categories)
    top = max(counts.values())

    return next(c for c in categories if counts[c] == top)
