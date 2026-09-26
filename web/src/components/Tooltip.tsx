import type { ReactNode } from "react";

interface Props {
  label: string;
  children: ReactNode;
  // "start"/"end" anchor the tooltip's leading/trailing edge to the trigger instead
  // of centering it — use them for triggers near the edge of the viewport/panel,
  // where a centered tooltip would run off-screen (e.g. the last column of the
  // transactions table, or a button straddling the input's corner).
  align?: "center" | "start" | "end";
  // "bottom" opens the tooltip downward instead of upward — use it for triggers near
  // the top of the viewport (e.g. the header), where an upward tooltip gets clipped.
  side?: "top" | "bottom";
  // Extra classes on the wrapper — e.g. "w-full" so it stretches to fill a table
  // cell instead of shrinking to the trigger's own intrinsic width.
  className?: string;
}

// A plain title="..." tooltip waits out the browser's fixed native delay
// (~1-1.5s) before showing — this fades in almost immediately on hover instead.
export default function Tooltip({ label, children, align = "center", side = "top", className = "" }: Props) {
  const position = align === "end" ? "end-0" : align === "start" ? "start-0" : "start-1/2 -translate-x-1/2";
  const sideClasses = side === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";
  return (
    <div className={`group relative inline-flex ${className}`}>
      {children}
      <span
        className={`pointer-events-none absolute ${sideClasses} ${position} z-20 whitespace-nowrap rounded-md bg-zinc-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity duration-100 group-hover:opacity-100 dark:bg-zinc-700`}
      >
        {label}
      </span>
    </div>
  );
}
