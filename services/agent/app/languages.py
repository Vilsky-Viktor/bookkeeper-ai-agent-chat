"""Supported UI/chat/receipt languages — the settings dropdown offers exactly these,
and the backend rejects anything else (see main.py's preferences endpoint). Also
listed in web/src/lib/i18n/languages.ts and chat/receipt_turn.py's replies;
tests/test_contracts.py fails if they drift."""

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
