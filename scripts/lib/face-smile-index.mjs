// Loads the face/smile detector output (scripts/detect_faces_smiles.py ->
// face_smile_full.ndjson) into an index the prettiness scorer joins as an overlay,
// so face_visible_score and smile_score light up without a CV-checkpoint rebuild.
//
// Keyed by image id (face + smile are per-image, like the crop). review_row_key is
// also indexed as a fallback join. Occluded mouths already carry smile_score 0 from
// the detector; this loader passes the values through and exposes the flags.

import { readFile, stat } from "node:fs/promises";

// id -> { has_face, face_conf, smile_score, mouth_occluded, face_frac }
export async function loadFaceSmileIndex(ndjsonPath) {
  await stat(ndjsonPath).catch(() => {
    throw new Error(`face/smile ndjson not found: ${ndjsonPath}`);
  });
  const raw = await readFile(ndjsonPath, "utf8");
  const byId = {};
  const byKey = {};
  let rows = 0;
  let withFace = 0;
  for (const line of raw.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    let r;
    try {
      r = JSON.parse(t);
    } catch {
      continue;
    }
    rows += 1;
    const entry = {
      has_face: r.has_face === true ? true : r.has_face === false ? false : null,
      face_conf: Number.isFinite(r.face_conf) ? r.face_conf : null,
      face_frac: Number.isFinite(r.face_frac) ? r.face_frac : null,
      // The detector zeroes smile_score when the mouth is occluded; keep that.
      smile_score: Number.isFinite(r.smile_score) ? r.smile_score : null,
      mouth_occluded: Boolean(r.mouth_occluded),
    };
    if (entry.has_face) withFace += 1;
    if (r.id) byId[String(r.id)] = entry;
    if (r.review_row_key) byKey[String(r.review_row_key)] = entry;
  }
  return { byId, byKey, meta: { ndjson: ndjsonPath, rows, with_face: withFace } };
}
