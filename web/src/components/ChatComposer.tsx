import { ArrowUpIcon, MicIcon, PaperclipIcon, SquareIcon } from "lucide-react";
import { useRef } from "react";
import type { ComponentProps, RefObject } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useTranslation } from "@/lib/i18n";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onFileSelected: (file: File) => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  streaming: boolean;
  recording: boolean;
  transcribing: boolean;
  micButtonProps: Pick<ComponentProps<"button">, "onPointerDown" | "onPointerUp" | "onPointerCancel" | "onContextMenu">;
}

/** The message box, as the prepza project's description box: a rounded field that turns
 * blue on focus, with attach and hold-to-record on the start side and the send arrow on
 * the end. */
export default function ChatComposer({
  value,
  onChange,
  onSend,
  onFileSelected,
  textareaRef,
  streaming,
  recording,
  transcribing,
  micButtonProps,
}: Props) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const busy = streaming || transcribing;

  return (
    <div className="shrink-0 p-3 pt-0">
      {transcribing && (
        <div className="mb-2 flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <MicIcon className="size-4 animate-pulse" />
          <span className="animate-pulse">{t("transcribing")}</span>
        </div>
      )}
      <div className="w-full rounded-3xl border border-transparent bg-muted p-3 transition-colors focus-within:border-ring dark:bg-input/30">
        <Textarea
          ref={textareaRef}
          placeholder={t("chatPlaceholder")}
          value={value}
          disabled={busy}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !streaming) {
              e.preventDefault(); // Enter sends; Shift+Enter for a newline
              onSend();
            }
          }}
          className="max-h-48 min-h-12 resize-none border-0 bg-transparent p-2 text-base shadow-none focus-visible:ring-0 md:text-sm dark:bg-transparent"
        />
        <input
          type="file"
          accept="image/*,application/pdf"
          ref={fileInputRef}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = ""; // so picking the same file again still fires onChange
            if (file) onFileSelected(file);
          }}
        />
        <div className="flex items-center gap-1 pt-2">
          <Button
            variant="ghost"
            size="icon-lg"
            className="rounded-full text-muted-foreground"
            onClick={() => fileInputRef.current?.click()}
            disabled={busy || recording}
            aria-label={t("uploadReceipt")}
          >
            <PaperclipIcon />
          </Button>
          <Button
            {...micButtonProps}
            variant={recording ? "destructive" : "ghost"}
            size="icon-lg"
            className={`touch-none rounded-full select-none ${recording ? "animate-pulse" : "text-muted-foreground"}`}
            disabled={busy}
            aria-label={recording ? t("stopRecording") : t("recordVoice")}
          >
            {recording ? <SquareIcon className="fill-current" /> : <MicIcon />}
          </Button>
          <Button
            size="icon-lg"
            className="ms-auto rounded-full"
            onClick={onSend}
            disabled={busy || !value.trim()}
            aria-label={t("send")}
          >
            <ArrowUpIcon />
          </Button>
        </div>
      </div>
    </div>
  );
}
