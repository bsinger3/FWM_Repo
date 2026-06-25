// Intrinsic image dimensions from header bytes — no full decode, no `sharp`.
//
// Parses width/height out of the leading bytes of JPEG / PNG / WebP / GIF files.
// A small range-fetched prefix (a few KB) is enough for every format here; the
// SOF marker in progressive JPEGs can sit deeper, so fetch ~1MB to be safe.
//
// (The JPEG/PNG/WebP parsers mirror the ones in score-dev-image-prettiness.mjs,
// kept standalone here so the dimension backfill doesn't depend on the prettiness
// pipeline. GIF support is added because a handful of CDN sources serve GIFs.)

export function parseJpegMetadata(buffer) {
  if (buffer.length < 4 || buffer[0] !== 0xff || buffer[1] !== 0xd8) return {};
  const sofMarkers = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);
  let offset = 2;
  const metadata = { format: "jpeg", width: null, height: null };
  while (offset + 4 <= buffer.length) {
    if (buffer[offset] !== 0xff) {
      offset += 1;
      continue;
    }
    const marker = buffer[offset + 1];
    offset += 2;
    if (marker === 0xda || marker === 0xd9) break;
    if (offset + 2 > buffer.length) break;
    const segmentLength = buffer.readUInt16BE(offset);
    const segmentStart = offset + 2;
    const segmentEnd = offset + segmentLength;
    if (segmentEnd > buffer.length) break;
    if (sofMarkers.has(marker) && segmentStart + 7 <= buffer.length) {
      metadata.height = buffer.readUInt16BE(segmentStart + 1);
      metadata.width = buffer.readUInt16BE(segmentStart + 3);
    }
    offset = segmentEnd;
  }
  return metadata;
}

export function parsePngMetadata(buffer) {
  const signature = "89504e470d0a1a0a";
  if (buffer.length < 24 || buffer.subarray(0, 8).toString("hex") !== signature) return {};
  if (buffer.toString("ascii", 12, 16) !== "IHDR") return {};
  return { format: "png", width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

export function parseWebpMetadata(buffer) {
  if (buffer.length < 30) return {};
  if (buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WEBP") return {};
  const fourcc = buffer.toString("ascii", 12, 16);
  const meta = { format: "webp", width: null, height: null };
  if (fourcc === "VP8 ") {
    // Lossy: 14-bit dimensions at byte 26 (width) and 28 (height).
    meta.width = buffer.readUInt16LE(26) & 0x3fff;
    meta.height = buffer.readUInt16LE(28) & 0x3fff;
  } else if (fourcc === "VP8L") {
    // Lossless: 14-bit dimensions packed after the 0x2f signature byte.
    const bits = buffer.readUInt32LE(21);
    meta.width = (bits & 0x3fff) + 1;
    meta.height = ((bits >> 14) & 0x3fff) + 1;
  } else if (fourcc === "VP8X") {
    // Extended: 24-bit canvas dimensions minus one at byte 24/27.
    meta.width = (buffer[24] | (buffer[25] << 8) | (buffer[26] << 16)) + 1;
    meta.height = (buffer[27] | (buffer[28] << 8) | (buffer[29] << 16)) + 1;
  }
  return meta;
}

export function parseGifMetadata(buffer) {
  if (buffer.length < 10) return {};
  const sig = buffer.toString("ascii", 0, 6);
  if (sig !== "GIF87a" && sig !== "GIF89a") return {};
  // Logical screen descriptor: width/height are little-endian uint16 at byte 6/8.
  return { format: "gif", width: buffer.readUInt16LE(6), height: buffer.readUInt16LE(8) };
}

// Sniff format from magic bytes first (most reliable), fall back to content-type.
export function parseImageMetadata(buffer, contentType) {
  const lowerType = String(contentType || "").toLowerCase();
  if (buffer.length >= 12 && buffer.subarray(0, 4).toString("ascii") === "RIFF" && buffer.subarray(8, 12).toString("ascii") === "WEBP") {
    return parseWebpMetadata(buffer);
  }
  if (buffer.length >= 8 && buffer.subarray(0, 8).toString("hex") === "89504e470d0a1a0a") {
    return parsePngMetadata(buffer);
  }
  if (buffer.length >= 6 && buffer.toString("ascii", 0, 3) === "GIF") {
    return parseGifMetadata(buffer);
  }
  if (buffer.length >= 2 && buffer[0] === 0xff && buffer[1] === 0xd8) {
    return parseJpegMetadata(buffer);
  }
  // No magic match — trust the declared content-type as a last resort.
  if (lowerType.includes("png")) return parsePngMetadata(buffer);
  if (lowerType.includes("webp")) return parseWebpMetadata(buffer);
  if (lowerType.includes("gif")) return parseGifMetadata(buffer);
  return parseJpegMetadata(buffer);
}
