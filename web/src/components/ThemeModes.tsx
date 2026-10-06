import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { useTranslation } from "@/lib/i18n";

const modes = [
  { value: "system", icon: MonitorIcon, label: "systemTheme" },
  { value: "light", icon: SunIcon, label: "lightMode" },
  { value: "dark", icon: MoonIcon, label: "darkMode" },
] as const;

/** System, light and dark side by side, as in the prepza project's user menu. */
export function ThemeModes() {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();

  return (
    <div className="flex w-full gap-1" role="group" aria-label={t("theme")}>
      {modes.map(({ value, icon: Icon, label }) => (
        <Button
          key={value}
          type="button"
          variant={theme === value ? "secondary" : "ghost"}
          className="h-8 flex-1 shrink"
          aria-label={t(label)}
          tooltip={t(label)}
          aria-pressed={theme === value}
          onClick={() => setTheme(value)}
        >
          <Icon />
        </Button>
      ))}
    </div>
  );
}
