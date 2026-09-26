import { Download, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { parseCsvPreviewRows } from "../lib/csv";

interface Props {
  url: string;
  filename: string;
}

const PREVIEW_ROWS = 6;
const PREVIEW_COLS = 4;
// The mini-table is laid out at a normal, legible size, then scaled down as a whole
// via CSS transform to fit the 88px square — the same "render then shrink" idea as
// ReceiptThumb's PDF page preview, just with real HTML instead of a canvas.
const PREVIEW_VIRTUAL_WIDTH = 220;
const PREVIEW_SCALE = 88 / PREVIEW_VIRTUAL_WIDTH;

// A click-to-download attachment, e.g. an exported CSV — built once when the export
// happens (see ChatPanel's export_ready handling) and stays downloadable for the rest
// of the session via a blob object URL. Same squared tile + hover affordance as
// ReceiptThumb's image/PDF preview; the square shows an actual preview of the CSV's
// first few rows once fetched, falling back to a generic file icon until then (or if
// fetching/parsing it ever fails).
export default function FileAttachment({ url, filename }: Props) {
  const [rows, setRows] = useState<string[][] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((res) => res.text())
      .then((text) => {
        if (!cancelled) setRows(parseCsvPreviewRows(text, PREVIEW_ROWS, PREVIEW_COLS));
      })
      .catch(() => {
        // best effort — the generic file icon below stays as the fallback
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return (
    <a
      href={url}
      download={filename}
      aria-label={filename}
      title={filename}
      className="group relative inline-flex h-[88px] w-[88px] items-center justify-center overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900"
    >
      {rows && rows.length > 0 ? (
        <table
          className="absolute left-0 top-0 origin-top-left border-collapse text-[11px] leading-tight text-zinc-500 dark:text-zinc-400"
          style={{ width: PREVIEW_VIRTUAL_WIDTH, transform: `scale(${PREVIEW_SCALE})` }}
        >
          <tbody>
            {rows.map((cells, i) => (
              <tr key={i} className={i === 0 ? "font-semibold text-zinc-700 dark:text-zinc-200" : undefined}>
                {cells.map((cell, j) => (
                  <td key={j} className="max-w-[55px] truncate border border-zinc-100 px-1 py-0.5 dark:border-zinc-800">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <FileText size={32} className="text-zinc-400 dark:text-zinc-600" />
      )}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
        <Download size={20} className="text-white" />
      </div>
    </a>
  );
}
