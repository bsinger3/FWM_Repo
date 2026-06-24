#!/usr/bin/env node
/**
 * Re-parse the already-harvested Reddit posts with the CURRENT extractor and
 * print summary statistics. Re-uses the raw text stored on each record, so it
 * does NOT re-fetch Reddit (no rate-limit cost) and writes NOTHING to Supabase.
 *
 * Input:  FWM_Data/reddit_harvest/posts.ndjson  (raw harvest, append-only)
 * Output: FWM_Data/reddit_harvest/posts_clean.ndjson  (re-parsed, off-intent
 *         dropped, bounds-checked measurements) — for human review before any load.
 *
 * Usage: node scripts/reparse-and-stats-reddit.mjs
 */
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { extractMeasurements, looksOffIntent } from "./harvest-reddit-posts.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIR = resolve(__dirname, "../../FWM_Data/reddit_harvest");
const IN = resolve(DIR, "posts.ndjson");
const OUT = resolve(DIR, "posts_clean.ndjson");

const MEAS_KEYS = ["height_in", "weight_lbs", "bra_size", "bust_in", "chest_in", "waist_in", "hips_in", "inseam_in"];

// Lightweight clothing-request classifier — for the stats summary only (the DB
// column stays null for now). A post can match several buckets.
const CLOTHING = [
  ["bras/lingerie", /\b(bra|bras|lingerie|underwire|bralette|underband|sports? bra)\b/i],
  ["swimwear", /\b(swim|swimsuit|bikini|tankini|one[- ]?piece|bathing suit)\b/i],
  ["jeans/denim", /\b(jeans?|denim)\b/i],
  ["pants/trousers", /\b(pants|trousers|slacks|leggings|chinos)\b/i],
  ["shorts", /\b(shorts)\b/i],
  ["dresses", /\b(dress|dresses|gown|sundress)\b/i],
  ["skirts", /\b(skirt|skirts)\b/i],
  ["tops/shirts", /\b(top|tops|shirt|blouse|tee|t-shirt|tank|sweater|cardigan|knit)\b/i],
  ["outerwear", /\b(coat|jacket|blazer|outerwear|parka)\b/i],
  ["suits/formal", /\b(suit|tuxedo|formal|blazer|interview outfit)\b/i],
  ["activewear", /\b(activewear|gym|workout|athletic|yoga|running)\b/i],
  ["maternity", /\b(maternity|pregnan|bump|postpartum|nursing)\b/i],
  ["wedding/event", /\b(wedding|bridal|bridesmaid|graduation|prom|gala|cocktail)\b/i],
  ["full outfit/styling", /\b(outfit|capsule wardrobe|style me|what (?:to|should i) wear|how to dress|body type|kibbe)\b/i],
];
function classifyClothing(text) {
  const hits = CLOTHING.filter(([, re]) => re.test(text)).map(([k]) => k);
  return hits.length ? hits : ["(unclassified)"];
}

const pct = (n, d) => (d ? `${((n / d) * 100).toFixed(0)}%` : "0%");
const bar = (n, max, width = 28) => "█".repeat(Math.round((n / max) * width)).padEnd(width, "·");

async function main() {
  const rows = (await readFile(IN, "utf8")).split("\n").filter(Boolean).map((l) => JSON.parse(l));
  const now = Date.now();

  const clean = [];
  let droppedOffIntent = 0;
  for (const r of rows) {
    const text = `${r.title || ""}\n${r.raw_text || ""}`;
    if (looksOffIntent(text)) {
      droppedOffIntent++;
      continue;
    }
    const measurements = extractMeasurements(text);
    const has = MEAS_KEYS.some((k) => measurements[k] !== undefined);
    clean.push({
      ...r,
      has_measurements: has,
      measurements: has ? measurements : null,
      clothing_request: classifyClothing(text), // stats aid; not for DB
    });
  }

  await writeFile(OUT, clean.map((c) => JSON.stringify(c)).join("\n") + "\n", "utf8");

  // ---------- stats ----------
  const withMeas = clean.filter((c) => c.has_measurements);
  const out = [];
  out.push(`\n${"=".repeat(60)}`);
  out.push(`RE-PARSED ${rows.length} raw posts → ${clean.length} kept, ${droppedOffIntent} off-intent dropped`);
  out.push(`With measurements: ${withMeas.length} (${pct(withMeas.length, clean.length)})`);
  out.push("=".repeat(60));

  // 1. posts per subreddit
  const bySub = {};
  for (const c of clean) {
    bySub[c.subreddit] ||= { posts: 0, meas: 0, img: 0 };
    bySub[c.subreddit].posts++;
    if (c.has_measurements) bySub[c.subreddit].meas++;
    if ((c.image_urls || []).length) bySub[c.subreddit].img++;
  }
  const subs = Object.entries(bySub).sort((a, b) => b[1].posts - a[1].posts);
  const maxP = Math.max(...subs.map(([, v]) => v.posts));
  out.push(`\n— POSTS BY SUBREDDIT —`);
  out.push(`${"subreddit".padEnd(22)} ${"posts".padStart(5)} ${"meas".padStart(5)} ${"img".padStart(5)}  distribution`);
  for (const [s, v] of subs) {
    out.push(`${("r/" + s).padEnd(22)} ${String(v.posts).padStart(5)} ${String(v.meas).padStart(5)} ${String(v.img).padStart(5)}  ${bar(v.posts, maxP)}`);
  }

  // 2. age distribution
  const buckets = [
    ["< 24h", 0, 1], ["1–3 days", 1, 3], ["3–7 days", 3, 7],
    ["1–2 wks", 7, 14], ["2–4 wks", 14, 28], ["> 4 wks", 28, Infinity],
  ];
  const ageCount = Object.fromEntries(buckets.map((b) => [b[0], 0]));
  let oldest = 0;
  for (const c of clean) {
    const days = (now - Date.parse(c.created_utc)) / 86400000;
    oldest = Math.max(oldest, days);
    for (const [label, lo, hi] of buckets) if (days >= lo && days < hi) { ageCount[label]++; break; }
  }
  const maxA = Math.max(...Object.values(ageCount));
  out.push(`\n— POST AGE (from now) —`);
  for (const [label] of buckets) {
    out.push(`${label.padEnd(10)} ${String(ageCount[label]).padStart(5)}  ${bar(ageCount[label], maxA)}`);
  }
  out.push(`oldest post: ${oldest.toFixed(0)} days`);

  // 3. clothing request type
  const cloth = {};
  for (const c of clean) for (const k of c.clothing_request) cloth[k] = (cloth[k] || 0) + 1;
  const clothS = Object.entries(cloth).sort((a, b) => b[1] - a[1]);
  const maxC = Math.max(...clothS.map(([, v]) => v));
  out.push(`\n— CLOTHING / REQUEST TYPE (posts may match >1) —`);
  for (const [k, v] of clothS) {
    out.push(`${k.padEnd(22)} ${String(v).padStart(5)}  ${bar(v, maxC)}`);
  }

  // 4. which measurements are provided
  const mc = Object.fromEntries(MEAS_KEYS.map((k) => [k, 0]));
  const counts = [];
  for (const c of withMeas) {
    let n = 0;
    for (const k of MEAS_KEYS) if (c.measurements[k] !== undefined) { mc[k]++; n++; }
    counts.push(n);
  }
  const maxM = Math.max(...Object.values(mc), 1);
  out.push(`\n— MEASUREMENTS PROVIDED (of ${withMeas.length} measured posts) —`);
  for (const k of MEAS_KEYS) {
    out.push(`${k.padEnd(12)} ${String(mc[k]).padStart(5)} ${pct(mc[k], withMeas.length).padStart(5)}  ${bar(mc[k], maxM)}`);
  }
  const avg = counts.length ? (counts.reduce((a, b) => a + b, 0) / counts.length).toFixed(1) : 0;
  const full = withMeas.filter((c) => ["height_in", "bust_in", "waist_in", "hips_in"].every((k) => c.measurements[k] !== undefined)).length;
  out.push(`\navg measurements per measured post: ${avg}`);
  out.push(`posts with full H/B/W/H set: ${full}`);

  out.push(`\nCleaned file written: ${OUT}`);
  out.push(`(nothing written to Supabase)`);
  console.log(out.join("\n"));
}

main().catch((e) => { console.error(e); process.exit(1); });
