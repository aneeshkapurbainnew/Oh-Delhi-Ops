/**
 * Shrink a bill photo before upload: longest side 1600px, JPEG quality 0.72 (~150-300 KB).
 * Keeps Supabase's free 1 GB of storage good for thousands of bills. PDFs and images the browser
 * can't decode (e.g. HEIC outside Safari) are uploaded unchanged.
 */
export async function compressImage(file, maxSide = 1600, quality = 0.72) {
  if (!file || !file.type.startsWith("image/") || file.size < 250 * 1024) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", quality));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return file;
  }
}
