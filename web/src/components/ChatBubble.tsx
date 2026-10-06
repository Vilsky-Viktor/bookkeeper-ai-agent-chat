import type { ReactNode } from "react";

/** One chat message: the user's on the end side in a muted bubble, the assistant's on the
 * start side, after the prepza project's chat. */
export function ChatBubble({ role, children }: { role: "user" | "assistant"; children: ReactNode }) {
  return (
    <div
      className={`w-fit max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
        role === "user" ? "bg-muted" : "bg-background/40"
      }`}
    >
      {children}
    </div>
  );
}

/** The assistant's bubble before its first words arrive: three dots rising in turn. */
export function ThinkingBubble({ label }: { label: string }) {
  return (
    <div className="flex w-fit items-center gap-1 self-start rounded-2xl bg-background/40 px-4 py-4">
      <span className="sr-only">{label}</span>
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          aria-hidden
          className="size-1.5 animate-[thinking_1.2s_ease-in-out_infinite] rounded-full bg-muted-foreground"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  );
}
