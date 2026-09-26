import { Mic, Paperclip, Square } from "lucide-react";
import { useRef } from "react";
import type { ComponentProps, RefObject } from "react";
import { useTranslation } from "../lib/i18n";
import Tooltip from "./Tooltip";

const circleButton =
  "flex h-12 w-12 items-center justify-center rounded-full shadow-md transition-colors disabled:cursor-not-allowed disabled:opacity-50";
const idleCircle =
  "bg-white text-sky-600 ring-1 ring-zinc-200 hover:bg-sky-50 dark:bg-zinc-800 dark:text-sky-400 dark:ring-zinc-700 dark:hover:bg-sky-950/40";

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

/** The message box, with the receipt-upload and hold-to-record buttons on its corners. */
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

  return (
    <div className="relative z-10 shrink-0 rounded-xl bg-white pt-4 pb-8 ps-8 pe-8 shadow-sm dark:bg-zinc-900">
      {transcribing && (
        <div className="mb-1.5 flex items-center justify-center gap-2 text-base text-zinc-400 dark:text-zinc-600">
          <Mic size={18} className="animate-pulse" />
          <span className="animate-pulse">{t("transcribing")}</span>
        </div>
      )}
      <div className="relative">
        {/* The frame and the <textarea> are separate elements, with a fixed strip of
            dead space below the textarea inside the frame. Padding on the textarea
            alone isn't enough: once text overflows, the browser scrolls to keep the
            caret visible and the padding scrolls away, so text would slide under the
            corner buttons. A sibling element can never be scrolled into. */}
        <div className="rounded-lg border border-zinc-200 bg-white focus-within:ring-1 focus-within:ring-sky-500/40 dark:border-zinc-700 dark:bg-zinc-900">
          <textarea
            ref={textareaRef}
            rows={4}
            placeholder={t("chatPlaceholder")}
            value={value}
            disabled={streaming || transcribing}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !streaming) {
                e.preventDefault(); // Enter sends; Shift+Enter for a newline
                onSend();
              }
            }}
            className="block w-full resize-none border-0 bg-transparent pt-4 ps-5 pe-5 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none disabled:opacity-50 dark:text-zinc-100 dark:placeholder-zinc-600"
          />
          <div className="h-10" aria-hidden="true" />
        </div>
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
        {/* The attach and mic circles straddle the frame's bottom corners. The absolute
            positioning is on a wrapper outside each Tooltip: Tooltip's root is
            `relative` (to anchor its bubble), so positioning the button itself would
            make the Tooltip, not this frame, the reference. */}
        <div className="absolute bottom-0 start-0 translate-x-[-35%] translate-y-[35%]">
          <Tooltip label={t("uploadReceipt")} align="start">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={streaming || recording || transcribing}
              aria-label={t("uploadReceipt")}
              className={`${circleButton} ${idleCircle}`}
            >
              <Paperclip size={20} />
            </button>
          </Tooltip>
        </div>
        <div className="absolute bottom-0 end-0 translate-x-[35%] translate-y-[35%]">
          <Tooltip label={recording ? t("stopRecording") : t("recordVoice")} align="end">
            <button
              {...micButtonProps}
              disabled={streaming || transcribing}
              aria-label={recording ? t("stopRecording") : t("recordVoice")}
              className={`${circleButton} touch-none select-none ${
                recording ? "animate-pulse bg-red-600 text-white hover:bg-red-500" : idleCircle
              }`}
            >
              {recording ? <Square size={17} fill="currentColor" /> : <Mic size={22} />}
            </button>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
