from app.languages import SUPPORTED_LANGUAGES


class TestSupportedLanguages:
    def test_contains_english_default(self):
        assert SUPPORTED_LANGUAGES["en"] == "English"

    def test_all_ten_languages_present(self):
        assert len(SUPPORTED_LANGUAGES) == 10

    def test_codes_are_lowercase_two_letter(self):
        assert all(len(code) == 2 and code.islower() for code in SUPPORTED_LANGUAGES)
