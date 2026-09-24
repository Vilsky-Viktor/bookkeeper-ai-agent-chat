import type { ReactNode } from "react";
import Tooltip from "./Tooltip";

interface Props {
  onClick: () => void;
  label: string;
  children: ReactNode;
  align?: "center" | "end";
  side?: "top" | "bottom";
}

export default function IconButton({ onClick, label, children, align, side }: Props) {
  return (
    <Tooltip label={label} align={align} side={side}>
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        className="inline-flex h-6 w-6 items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-sky-50 hover:text-sky-600 dark:text-zinc-600 dark:hover:bg-sky-950/40 dark:hover:text-sky-400"
      >
        {children}
      </button>
    </Tooltip>
  );
}
