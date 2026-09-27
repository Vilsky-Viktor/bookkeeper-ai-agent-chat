"""The languages the web app offers (web/src/lib/i18n/languages.ts;
tests/test_contracts.py fails if they drift): the preferences endpoint rejects
anything else. Not translations — those all live in the web app. The names are how
prompts tell a model which language to write in ("Reply in Ukrainian")."""

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "id": "Indonesian",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "he": "Hebrew",
    "ru": "Russian",
    "uk": "Ukrainian",
    "ar": "Arabic",
}
