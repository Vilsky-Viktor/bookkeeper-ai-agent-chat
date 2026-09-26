const TARGET_WIDTH_PX = 240; // ~2.7x an 88px CSS square, sharp on retina displays

let workerConfigured = false;

// Renders a PDF's first page to a PNG data URL — used as ReceiptThumb's square
// preview for a PDF receipt, the same way a photo receipt just uses its own URL
// directly. Same-origin `url` (routed through Caddy locally / Firebase Hosting in
// production), so no CORS configuration is needed for pdf.js's own fetch.
//
// pdfjs-dist is dynamically imported (~1.2MB minified, plus its own similarly-sized
// worker) so its cost only lands on someone who actually receives a PDF receipt —
// everyone else's bundle stays untouched. Vite code-splits a dynamic import()
// automatically, unlike a static top-level import.
export async function renderPdfFirstPageToDataUrl(url: string): Promise<string> {
  const { GlobalWorkerOptions, getDocument } = await import("pdfjs-dist");
  if (!workerConfigured) {
    // Same Vite-specific pattern as the dynamic import above: bundles the worker as
    // its own asset with a correct hashed URL, in both dev and a production build.
    GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).href;
    workerConfigured = true;
  }

  const pdf = await getDocument({ url }).promise;
  const page = await pdf.getPage(1);

  const unscaledViewport = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: TARGET_WIDTH_PX / unscaledViewport.width });

  const canvas = document.createElement("canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  const canvasContext = canvas.getContext("2d");
  if (!canvasContext) throw new Error("2D canvas context unavailable");

  await page.render({ canvas, canvasContext, viewport }).promise;
  return canvas.toDataURL("image/png");
}
