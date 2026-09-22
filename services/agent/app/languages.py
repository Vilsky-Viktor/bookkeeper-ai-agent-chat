"""Supported UI/chat/receipt languages — the settings dropdown offers exactly these,
and the backend rejects anything else (see main.py's preferences endpoint)."""

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
