import { useCallback, useEffect, useRef, useState } from "react";

interface UseResizableOptions {
  axis: "x" | "y";
  initial: number;
  min: number;
  max: number;
  storageKey?: string;
  // false (default): the resized pane sits BEFORE the handle (e.g. left of a
  // vertical handle) — dragging toward positive x/y grows it. true: the pane sits
  // AFTER the handle (e.g. below a horizontal handle) — its leading edge follows the
  // handle, so dragging toward positive x/y should shrink it instead.
  reverse?: boolean;
}

// A draggable split — `size` is the primary pane's extent along `axis` (width for
// "x", height for "y"); the sibling pane is expected to be `flex-1` and take
// whatever's left. Persisted to localStorage per axis so a reload/orientation change
// doesn't reset it back to `initial`.
export function useResizable({ axis, initial, min, max, storageKey, reverse = false }: UseResizableOptions) {
  const [size, setSize] = useState<number>(() => {
    if (!storageKey) return initial;
    try {
      const stored = Number(localStorage.getItem(storageKey));
      return Number.isFinite(stored) && stored > 0 ? stored : initial;
    } catch {
      return initial;
    }
  });
  const dragState = useRef<{ startPos: number; startSize: number } | null>(null);

  useEffect(() => {
    if (!storageKey) return;
    try {
      localStorage.setItem(storageKey, String(size));
    } catch {
      // ignore — the size just won't persist across reloads
    }
  }, [size, storageKey]);

  const clamp = useCallback((v: number) => Math.min(max, Math.max(min, v)), [min, max]);

  // Re-clamp whenever the bounds themselves change (e.g. switching between the
  // mobile height-split and desktop width-split, which have different min/max), so a
  // size that was valid in one layout doesn't stay stuck out of range in the other.
  useEffect(() => {
    setSize((s) => clamp(s));
  }, [clamp]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      dragState.current = { startPos: axis === "x" ? e.clientX : e.clientY, startSize: size };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [axis, size],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!dragState.current) return;
      const pos = axis === "x" ? e.clientX : e.clientY;
      const delta = pos - dragState.current.startPos;
      setSize(clamp(dragState.current.startSize + (reverse ? -delta : delta)));
    },
    [axis, clamp, reverse],
  );

  const onPointerUp = useCallback((e: React.PointerEvent<HTMLElement>) => {
    dragState.current = null;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      // already released
    }
  }, []);

  return { size, handleProps: { onPointerDown, onPointerMove, onPointerUp } };
}
