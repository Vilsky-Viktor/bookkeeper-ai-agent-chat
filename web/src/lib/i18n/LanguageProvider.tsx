import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { getPreferences, updatePreferences } from "../api";
import { LanguageContext } from "./context";
import { DIR_BY_LANGUAGE, LOCALES, isLanguage } from "./languages";
import type { Language, MessageKey } from "./languages";

function readCachedLanguage(): Language {
  try {
    const stored = localStorage.getItem("language");
    if (stored && isLanguage(stored)) return stored;
  } catch {
    // ignore — localStorage can throw in private/blocked-storage contexts
  }
  return "en";
}

function cacheLanguage(language: Language) {
  try {
    localStorage.setItem("language", language);
  } catch {
    // ignore
  }
}

export function LanguageProvider({ userId, children }: { userId: string | null; children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(readCachedLanguage);

  useEffect(() => {
    document.documentElement.dir = DIR_BY_LANGUAGE[language] ?? "ltr";
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    // The account's saved language (server-side) is authoritative; the cached value
    // above only avoids flashing English while this loads.
    if (!userId) return;
    getPreferences()
      .then((p) => {
        if (isLanguage(p.language)) {
          setLanguageState(p.language);
          cacheLanguage(p.language);
        }
      })
      .catch(() => {
        // best effort — stay on the cached/default language
      });
  }, [userId]);

  function setLanguage(l: string) {
    if (!isLanguage(l)) return;
    setLanguageState(l);
    cacheLanguage(l);
    updatePreferences({ language: l }).catch(() => {
      // best effort — the UI already switched; a failed save means it reverts on reload
    });
  }

  function t(key: MessageKey): string {
    return LOCALES[language].ui[key];
  }

  function tCategory(category: string): string {
    const labels: Record<string, string> = LOCALES[language].categories;
    return labels[category.toLowerCase()] ?? category;
  }

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t, tCategory }}>{children}</LanguageContext.Provider>
  );
}
