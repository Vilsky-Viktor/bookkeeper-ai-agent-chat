import { afterEach, describe, expect, it, vi } from "vitest";
import { MAX_RECEIPT_SIDE, fitWithin, prepareReceiptUpload } from "./receiptUpload";

function bitmap(width: number, height: number) {
  return { width, height, close: vi.fn() };
}

/** Stubs the browser image APIs jsdom lacks; returns what got drawn. */
function stubCanvas(decoded: ReturnType<typeof bitmap>) {
  vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue(decoded));
  const drawn: { width: number; height: number }[] = [];
  const ctx = { fillRect: vi.fn(), drawImage: vi.fn((_b, _x, _y, w, h) => drawn.push({ width: w, height: h })) };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (cb, type) {
    cb(new Blob(["jpeg"], { type }));
  });
  return drawn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("fitWithin", () => {
  it("scales the long side down to the bound, keeping the aspect ratio", () => {
    expect(fitWithin(3000, 4000, 1600)).toEqual({ width: 1200, height: 1600 });
    expect(fitWithin(4032, 3024, 1600)).toEqual({ width: 1600, height: 1200 });
  });

  it("never scales up", () => {
    expect(fitWithin(800, 600, 1600)).toEqual({ width: 800, height: 600 });
  });
});

describe("prepareReceiptUpload", () => {
  it("uploads a PDF unchanged, as a PDF", async () => {
    const pdf = new File(["%PDF"], "r.pdf", { type: "application/pdf" });
    expect(await prepareReceiptUpload(pdf)).toEqual({ body: pdf, contentType: "application/pdf" });
  });

  it("downscales a large photo to a JPEG within the bound", async () => {
    const decoded = bitmap(3024, 4032);
    const drawn = stubCanvas(decoded);
    const photo = new File(["x"], "r.png", { type: "image/png" });

    const { body, contentType } = await prepareReceiptUpload(photo);

    expect(contentType).toBe("image/jpeg");
    expect(body).not.toBe(photo);
    expect(body.type).toBe("image/jpeg");
    expect(drawn).toEqual([{ width: 1200, height: MAX_RECEIPT_SIDE }]);
    expect(decoded.close).toHaveBeenCalled();
  });

  it("keeps a JPEG that's already small enough as-is (no re-encoding loss)", async () => {
    stubCanvas(bitmap(1000, 1400));
    const photo = new File(["x"], "r.jpg", { type: "image/jpeg" });
    expect((await prepareReceiptUpload(photo)).body).toBe(photo);
  });

  it("uploads the original when the browser can't decode it", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn().mockRejectedValue(new Error("unsupported")));
    const photo = new File(["x"], "r.heic", { type: "image/heic" });
    expect((await prepareReceiptUpload(photo)).body).toBe(photo);
  });
});
