// Receipts are stored at this size: text stays legible, and a phone photo shrinks
// from several MB to a few hundred KB. The agent downsizes to the same bound before
// the vision call, so nothing it reads is lost.
export const MAX_RECEIPT_SIDE = 1600;
const JPEG_QUALITY = 0.85;

export type ReceiptContentType = "image/jpeg" | "application/pdf";

export function fitWithin(width: number, height: number, maxSide: number): { width: number; height: number } {
  const scale = Math.min(1, maxSide / Math.max(width, height));
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/** What to upload for a picked receipt: a photo downscaled to MAX_RECEIPT_SIDE and
 * re-encoded as JPEG (decoded with its EXIF rotation applied), a PDF unchanged. An
 * image the browser can't decode is uploaded as-is. */
export async function prepareReceiptUpload(file: File): Promise<{ body: Blob; contentType: ReceiptContentType }> {
  if (file.type === "application/pdf") return { body: file, contentType: "application/pdf" };
  const original = { body: file as Blob, contentType: "image/jpeg" as const };

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return original;
  }
  try {
    const within = bitmap.width <= MAX_RECEIPT_SIDE && bitmap.height <= MAX_RECEIPT_SIDE;
    if (within && file.type === "image/jpeg") return original; // re-encoding would only lose quality

    const { width, height } = fitWithin(bitmap.width, bitmap.height, MAX_RECEIPT_SIDE);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return original;
    ctx.fillStyle = "#fff"; // JPEG has no transparency; a transparent PNG would turn black
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(bitmap, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
    return blob ? { body: blob, contentType: "image/jpeg" } : original;
  } finally {
    bitmap.close();
  }
}
