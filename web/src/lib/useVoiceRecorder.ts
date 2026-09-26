import { useRef, useState } from "react";
import type { MouseEvent, PointerEvent } from "react";
import { transcribeAudio } from "./api";

interface Callbacks {
  onTranscript: (text: string) => void | Promise<void>; // non-empty, trimmed
  onError: () => void; // mic unavailable or transcription failed
}

/** Press-and-hold voice input: records while the button is held, then transcribes.
 * Spread `micButtonProps` onto the button. */
export function useVoiceRecorder({ onTranscript, onError }: Callbacks) {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  // Whether the pointer is still down through the async getUserMedia gap, so a very
  // quick tap (released before the permission prompt resolves) doesn't leave
  // recording stuck on with nothing to stop it.
  const holdingRef = useRef(false);

  async function startRecording() {
    holdingRef.current = true;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      onError();
      holdingRef.current = false;
      return;
    }
    if (!holdingRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    const mimeType = ["audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    audioChunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data);
    };
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      setRecording(false);
      const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
      if (blob.size === 0) return;
      setTranscribing(true);
      try {
        const { text } = await transcribeAudio(blob);
        if (text.trim()) {
          setTranscribing(false);
          await onTranscript(text.trim());
          return;
        }
      } catch {
        onError();
      }
      setTranscribing(false);
    };
    mediaRecorderRef.current = recorder;
    recorder.start();
    setRecording(true);
  }

  function handlePointerDown(e: PointerEvent<HTMLButtonElement>) {
    e.preventDefault(); // don't steal focus from the textarea or trigger text selection
    e.currentTarget.setPointerCapture(e.pointerId);
    startRecording();
  }

  function handlePointerUp(e: PointerEvent<HTMLButtonElement>) {
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      // already released
    }
    holdingRef.current = false;
    mediaRecorderRef.current?.stop();
  }

  return {
    recording,
    transcribing,
    micButtonProps: {
      onPointerDown: handlePointerDown,
      onPointerUp: handlePointerUp,
      onPointerCancel: handlePointerUp,
      onContextMenu: (e: MouseEvent<HTMLButtonElement>) => e.preventDefault(), // long-press menu on touch
    },
  };
}
