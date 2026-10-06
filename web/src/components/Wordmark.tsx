import { cn } from "cn";

/** "smaker." in the heading font with the dot in the brand blue, as the prepza project's
 * wordmark. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-heading font-semibold tracking-tight", className)}>
      smaker<span className="text-primary">.</span>
    </span>
  );
}
