import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem("theme");
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // private-mode/blocked storage — fall through to system preference
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Tailwind's class-based dark mode (see index.css's @custom-variant): toggling the
// `dark` class on <html> is what actually switches every dark: utility at once.
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem("theme", theme);
    } catch {
      // ignore — theme just won't persist across reloads
    }
  }, [theme]);

  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));
  return [theme, toggle];
}
