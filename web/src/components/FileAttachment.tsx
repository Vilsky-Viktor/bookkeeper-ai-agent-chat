import { FileText } from "lucide-react";

interface Props {
  url: string;
  filename: string;
}

// A click-to-download attachment, e.g. an exported CSV — built once when the export
// happens (see ChatPanel's export_ready handling) and stays downloadable for the rest
// of the session via a blob object URL.
export default function FileAttachment({ url, filename }: Props) {
  return (
    <a
      href={url}
      download={filename}
      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-700 transition-colors hover:bg-zinc-50 hover:text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
    >
      <FileText size={15} />
      <span>{filename}</span>
    </a>
  );
}
