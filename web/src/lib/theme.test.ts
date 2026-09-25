import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTheme } from "./theme";

function stubMatchMedia(prefersDark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: prefersDark,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

describe("useTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to the system preference when nothing is cached", () => {
    stubMatchMedia(true);
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("dark");
  });

  it("prefers a cached theme over the system preference", () => {
    stubMatchMedia(true); // system says dark...
    localStorage.setItem("theme", "light"); // ...but the user picked light before
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("light");
  });

  it("toggle() flips the theme, persists it, and toggles the <html> dark class", () => {
    stubMatchMedia(false);
    const { result } = renderHook(() => useTheme());

    expect(result.current[0]).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    act(() => result.current[1]());

    expect(result.current[0]).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("theme")).toBe("dark");
  });
});
