import datetime
import io
from unittest.mock import MagicMock

from PIL import Image

from app.helpers import images
from app.helpers.receipts import fold_merchant, majority_category
from app.services import receipts as receipts_module


class TestMajorityCategory:
    def test_most_common_wins(self):
        assert majority_category(["health", "groceries", "groceries"]) == "groceries"

    def test_tie_goes_to_the_first_on_the_receipt(self):
        assert majority_category(["shopping", "groceries", "groceries", "shopping"]) == "shopping"

    def test_empty_is_other(self):
        assert majority_category([]) == "other"


class TestReadReceipt:
    async def test_prompt_substitutes_placeholders_and_stays_locale_neutral(self, monkeypatch):
        captured = {}

        class _FakeVisionModel:
            async def ainvoke(self, messages, config=None):
                captured["prompt"] = messages[0].content[0]["text"]

                return MagicMock(content='{"is_receipt": false}')

        monkeypatch.setattr(receipts_module.llm, "vision_model", lambda: _FakeVisionModel())

        await receipts_module.read_receipt(b"imgdata", "image/jpeg", "en", datetime.date(2026, 9, 27))

        prompt = captured["prompt"]
        today = "2026-09-27"  # the user's date, not the server's
        assert today in prompt
        assert "{today}" not in prompt and "{language}" not in prompt
        # A relative date label ("Today, 5:52 PM") can only be resolved with today's date.
        assert "Today" in prompt and "Yesterday" in prompt
        assert 'set "merchant" to null' in prompt
        # The one amount read is the grand total — not the subtotal or cash tendered.
        assert '"total_paid"' in prompt
        assert "NOT the subtotal" in prompt
        # items drive the majority category: summary labels and fees in there once
        # voted a restaurant delivery order into "groceries" ("Price" vs "Handling and
        # delivery fee" vs "Other discounts", tie -> first).
        assert "list ONLY real" in prompt
        assert "never summary labels" in prompt
        # Receipts come from any country: describe line types by function, never one
        # locale's wording.
        assert "any language" in prompt

        for locale_specific in ("TUNAI", "KEMBALI", "HEMAT", "BELANJA", "PPN", "Indomaret", "rupiah"):
            assert locale_specific not in prompt


class TestReceiptNote:
    async def test_the_users_note_reaches_the_prompt_and_defaults_to_none(self, monkeypatch):
        prompts = []

        class _FakeVisionModel:
            async def ainvoke(self, messages, config=None):
                prompts.append(messages[0].content[0]["text"])

                return MagicMock(content='{"is_receipt": false}')

        monkeypatch.setattr(receipts_module.llm, "vision_model", lambda: _FakeVisionModel())

        await receipts_module.read_receipt(b"x", "image/jpeg", "en", datetime.date(2026, 9, 27), "this was yesterday")
        await receipts_module.read_receipt(b"x", "image/jpeg", "en", datetime.date(2026, 9, 27))

        assert "Note: this was yesterday" in prompts[0]
        assert "Note: (none)" in prompts[1]

    async def test_a_note_cant_fill_the_other_placeholders(self, monkeypatch):
        prompts = []

        class _FakeVisionModel:
            async def ainvoke(self, messages, config=None):
                prompts.append(messages[0].content[0]["text"])

                return MagicMock(content='{"is_receipt": false}')

        monkeypatch.setattr(receipts_module.llm, "vision_model", lambda: _FakeVisionModel())

        await receipts_module.read_receipt(b"x", "image/jpeg", "en", datetime.date(2026, 9, 27), "{today}")

        assert "Note: {today}" in prompts[0]


class TestFoldMerchant:
    def test_merchant_appended_when_not_already_in_description(self):
        assert fold_merchant("rice", "Alfamart") == "rice - Alfamart"

    def test_merchant_omitted_when_already_present(self):
        assert fold_merchant("rice from Alfamart", "Alfamart") == "rice from Alfamart"

    def test_no_merchant_returns_description_unchanged(self):
        assert fold_merchant("rice", None) == "rice"

    def test_no_description_returns_merchant(self):
        assert fold_merchant(None, "Alfamart") == "Alfamart"

    def test_neither_returns_none(self):
        assert fold_merchant(None, None) is None

    def test_literal_unknown_merchant_is_treated_as_no_merchant(self):
        # Observed: the model wrote "Unknown" as the merchant when it genuinely
        # couldn't read one, which folded in as "3x Camel White 20 - Unknown" — a
        # placeholder that looks like a real (wrong) merchant name.
        assert fold_merchant("3x Camel White 20", "Unknown") == "3x Camel White 20"

    def test_placeholder_merchant_case_insensitive(self):
        assert fold_merchant("rice", "UNKNOWN") == "rice"
        assert fold_merchant("rice", "N/A") == "rice"

    def test_unknown_merchant_with_no_description_returns_none(self):
        assert fold_merchant(None, "Unknown") is None


def _jpeg(width: int, height: int, orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    out = io.BytesIO()

    if orientation is None:
        img.save(out, format="JPEG")
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(out, format="JPEG", exif=exif)

    return out.getvalue()


class TestShrinkForVision:
    def test_caps_the_long_side_and_keeps_the_aspect_ratio(self):
        shrunk, content_type = images.shrink_for_vision(_jpeg(1200, 4000), "image/jpeg")
        assert content_type == "image/jpeg"

        with Image.open(io.BytesIO(shrunk)) as img:
            assert img.size == (480, images.MAX_IMAGE_SIDE)

    def test_leaves_a_small_image_at_its_size(self):
        shrunk, _ = images.shrink_for_vision(_jpeg(600, 900), "image/jpeg")

        with Image.open(io.BytesIO(shrunk)) as img:
            assert img.size == (600, 900)

    def test_applies_the_exif_rotation_before_dropping_the_tag(self):
        # Orientation 6 = "rotate 90° clockwise to display": a phone's portrait shot
        # stored landscape. Re-encoding without applying it sends a sideways receipt.
        shrunk, _ = images.shrink_for_vision(_jpeg(400, 300, orientation=6), "image/jpeg")

        with Image.open(io.BytesIO(shrunk)) as img:
            assert img.size == (300, 400)

    def test_undecodable_bytes_are_passed_through_unchanged(self):
        assert images.shrink_for_vision(b"not an image", "image/png") == (b"not an image", "image/png")
