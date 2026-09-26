import ar from "./locales/ar";
import de from "./locales/de";
import en from "./locales/en";
import type { Locale } from "./locales/en";
import es from "./locales/es";
import fr from "./locales/fr";
import he from "./locales/he";
import id from "./locales/id";
import pt from "./locales/pt";
import ru from "./locales/ru";
import uk from "./locales/uk";

// Must match services/agent/app/languages.py (the backend rejects anything else);
// that service's tests/test_contracts.py fails if they drift.
export const SUPPORTED_LANGUAGES: { code: string; label: string; dir: "ltr" | "rtl" }[] = [
  { code: "en", label: "English", dir: "ltr" },
  { code: "es", label: "Español", dir: "ltr" },
  { code: "id", label: "Bahasa Indonesia", dir: "ltr" },
  { code: "fr", label: "Français", dir: "ltr" },
  { code: "de", label: "Deutsch", dir: "ltr" },
  { code: "pt", label: "Português", dir: "ltr" },
  { code: "he", label: "עברית", dir: "rtl" },
  { code: "ru", label: "Русский", dir: "ltr" },
  { code: "uk", label: "Українська", dir: "ltr" },
  { code: "ar", label: "العربية", dir: "rtl" },
];

export const LOCALES = { en, es, id, fr, de, pt, he, ru, uk, ar } satisfies Record<string, Locale>;

export type Language = keyof typeof LOCALES;
export type MessageKey = keyof Locale["ui"];

export function isLanguage(l: string): l is Language {
  return l in LOCALES;
}

export const DIR_BY_LANGUAGE: Record<string, "ltr" | "rtl"> = Object.fromEntries(
  SUPPORTED_LANGUAGES.map((l) => [l.code, l.dir]),
);

// The stored category values (always the English keys) for building a category
// <select>. A transaction can also carry a custom category the user typed via a
// correction; that isn't in this list, so a dropdown must keep the current value as
// an extra option instead of silently dropping it.
export const BUILT_IN_CATEGORIES: string[] = Object.keys(en.categories);
