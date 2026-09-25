import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { LanguageProvider, useTranslation } from "./i18n";

// userId=null so LanguageProvider never fires its preferences fetch — these tests
// only exercise the cached-language read and the t/tCategory lookups.
function wrapper({ children }: { children: ReactNode }) {
  return <LanguageProvider userId={null}>{children}</LanguageProvider>;
}

describe("useTranslation", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to English when nothing is cached", () => {
    const { result } = renderHook(() => useTranslation(), { wrapper });
    expect(result.current.t("cancel")).toBe("Cancel");
  });

  it("picks up a previously cached language on mount", () => {
    localStorage.setItem("language", "es");
    const { result } = renderHook(() => useTranslation(), { wrapper });
    expect(result.current.t("cancel")).toBe("Cancelar");
  });

  it("ignores a cached value that isn't a supported language code", () => {
    localStorage.setItem("language", "klingon");
    const { result } = renderHook(() => useTranslation(), { wrapper });
    expect(result.current.t("cancel")).toBe("Cancel");
  });

  it("throws when used outside a LanguageProvider", () => {
    // Swallow the expected React error-boundary console noise for this one case.
    const { result } = renderHook(() => {
      try {
        return useTranslation();
      } catch (e) {
        return e;
      }
    });
    expect(result.current).toBeInstanceOf(Error);
  });

  describe("tCategory", () => {
    it("translates a known built-in category", () => {
      const { result } = renderHook(() => useTranslation(), { wrapper });
      expect(result.current.tCategory("groceries")).toBe("Groceries");
    });

    it("is case-insensitive", () => {
      const { result } = renderHook(() => useTranslation(), { wrapper });
      expect(result.current.tCategory("GROCERIES")).toBe("Groceries");
    });

    it("returns a user-defined category as-is (nothing to translate it from)", () => {
      const { result } = renderHook(() => useTranslation(), { wrapper });
      expect(result.current.tCategory("my custom category")).toBe("my custom category");
    });
  });
});
