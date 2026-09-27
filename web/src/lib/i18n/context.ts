import { createContext, useContext } from "react";
import type { Language, MessageKey } from "./languages";

export interface TranslationContext {
  language: Language;
  setLanguage: (l: string) => void;
  // `params` fill {name} placeholders, e.g. t("receiptProposed", { date }).
  t: (key: MessageKey, params?: Record<string, string>) => string;
  // A built-in category's label; a custom one is shown as-is (nothing to translate).
  tCategory: (category: string) => string;
}

export const LanguageContext = createContext<TranslationContext | null>(null);

export function useTranslation(): TranslationContext {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useTranslation must be used within a LanguageProvider");
  return ctx;
}
