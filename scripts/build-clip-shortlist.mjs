#!/usr/bin/env node

// Stage 1 of the CLIP-aesthetic "best photos" funnel. Ranks the eligible dev image
// pool by the "sellable photo" signals we ALREADY have (face + smile + full body,
// from the face/smile overlay and pose keypoints — no image re-download), and
// writes the top N to a shortlist ndjson for the CLIP aesthetic scorer (stage 2).
//
// Each shortlist row carries the autocrop rect (from crop_spec) so stage 2 can score
// the CARD the user actually sees. Read-only (no DB writes).
//
//   node scripts/build-clip-shortlist.mjs --top 1800 --out ../FWM_Data/_cache/clip_shortlist.ndjson

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import { assertApprovedDevSupabase } from "./lib/dev-supabase-guard.mjs";
import { loadFaceSmileIndex } from "./lib/face-smile-index.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const arg = (n, d) => {
  const m = process.argv.find((a) => a.startsWith(`--${n}=`));
  if (m) return m.slice(n.length + 3);
  const i = process.argv.indexOf(`--${n}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : d;
};
const TOP = Math.max(1, Number(arg("top", "1800")) || 1800);
const outPath = arg("out", path.join(fwmDataDir(repoRoot), "_cache", "clip_shortlist.ndjson"));

const FILTER =
  "original_url_display=not.is.null&size_display=not.is.null&size_display=neq.&size_display=neq.unknown" +
  "&removed_at=is.null&crop_spec=not.is.null" +
  "&or=(height_in_display.not.is.null,weight_display_display.not.is.null,bust_in_number_display.not.is.null,hips_in_display.not.is.null,waist_in.not.is.null)";

function cropRect(spec) {
  if (spec && (spec.mode === "cover-window" || spec.windowWPct != null)) {
    const c01 = (v) => Math.min(1, Math.max(0, Number(v) / 100));
    const widthFrac = c01(spec.windowWPct);
    const heightFrac = c01(spec.windowHPct);
    if (widthFrac && heightFrac) {
      return { leftFrac: c01(spec.windowXPct), topFrac: c01(spec.windowYPct), widthFrac, heightFrac };
    }
  }
  return null; // stage 2 falls back to the whole image
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  const H = { apikey: process.env.SUPABASE_SERVICE_ROLE_KEY, Authorization: `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY}` };

  console.log("Loading face/smile overlay + keypoint index...");
  const fs = await loadFaceSmileIndex(path.join(fwmDataDir(repoRoot), "_cache", "face_smile_full.ndjson"));
  const kp = JSON.parse(await readFile(path.join(fwmDataDir(repoRoot), "_cache", "keypoint_index.json"), "utf8")).byId;

  // Fetch the eligible pool (id, url, crop_spec), paged.
  const rows = [];
  const page = 1000;
  for (let offset = 0; ; offset += page) {
    const url = `${guard.supabaseUrl}/rest/v1/images?select=id,original_url_display,crop_spec&${FILTER}&order=id&limit=${page}&offset=${offset}`;
    const r = await fetch(url, { headers: H });
    const batch = await r.json();
    if (!Array.isArray(batch) || !batch.length) break;
    rows.push(...batch);
    if (batch.length < page) break;
    if (offset % 10000 === 0) console.log(`  fetched ${rows.length}...`);
  }
  console.log(`Eligible pool: ${rows.length}`);

  const present = (pt) => Array.isArray(pt) && pt[2] > 0.3;
  const scored = rows.map((row) => {
    const f = fs.byId[String(row.id)] || null;
    const k = kp[String(row.id)] || null;
    const hasFace = f && f.has_face === true;
    const smile = f && !f.mouth_occluded && Number.isFinite(f.smile_score) ? f.smile_score : 0;
    const single = k && k.person_count === 1;
    const kps = k && k.keypoints;
    const head = kps && present(kps.nose);
    const feet = kps && (present(kps.left_ankle) || present(kps.right_ankle));
    const fullBody = head && feet;
    // "Sellable photo" prior: a single person, full body, visible (ideally smiling) face.
    const score =
      (hasFace ? 1.0 : 0) + 1.6 * smile + (fullBody ? 1.2 : 0) + (single ? 0.5 : 0) + (head ? 0.3 : 0);
    return { id: row.id, url: row.original_url_display, crop: cropRect(row.crop_spec), stage1: Number(score.toFixed(3)) };
  });

  scored.sort((a, b) => b.stage1 - a.stage1);
  const top = scored.slice(0, TOP);
  await writeFile(outPath, top.map((r) => JSON.stringify(r)).join("\n") + "\n", "utf8");
  console.log(`Wrote ${top.length} -> ${outPath}`);
  console.log(`stage1 score at cutoff: top=${top[0].stage1}  #${TOP}=${top[top.length - 1].stage1}`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
