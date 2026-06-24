#!/usr/bin/env node
/**
 * Reddit post harvester for Friends With Measurements (FILE-FIRST, no DB).
 *
 * Why RSS and not the API: as of 2026 Reddit's "Responsible Builder Policy"
 * disabled self-serve script-app creation, and the unauthenticated .json
 * endpoints return 403. The public per-subreddit Atom feed
 * (https://www.reddit.com/r/<sub>/new/.rss) still works with no auth, no app,
 * and surfaces posts within ~1-2 hours of submission — fast enough for a 24h
 * response window. It is rate-limited (~1 req/min budget) so we pace + back off.
 *
 * What it does: rotate through a list of subreddits, pull each /new feed, parse
 * every post, extract body MEASUREMENTS (height/weight/bust/cup/waist/hips/
 * inseam) and IMAGE URLs, keep the posts that have either, dedupe across runs,
 * optionally verify that image URLs resolve, and append structured records to
 * an NDJSON file. Nothing is written to Supabase.
 *
 * Output (sibling FWM_Data, gitignored, outside the repo):
 *   ../FWM_Data/reddit_harvest/posts.ndjson        append-only, deduped records
 *   ../FWM_Data/reddit_harvest/_state/seen_ids.json dedup state (post fullnames)
 *   ../FWM_Data/reddit_harvest/runs/run_<ts>.json   per-run summary
 *
 * Usage:
 *   node scripts/harvest-reddit-posts.mjs
 *   node scripts/harvest-reddit-posts.mjs --subs=PetiteFashionAdvice,ABraThatFits
 *   node scripts/harvest-reddit-posts.mjs --tier=high        # only top-tier subs
 *   node scripts/harvest-reddit-posts.mjs --limit=100 --delay-ms=2500
 *   node scripts/harvest-reddit-posts.mjs --no-verify-images # skip image HEADs
 *   node scripts/harvest-reddit-posts.mjs --dry-run          # parse, don't write
 *
 * Read-only against Reddit. Polite by default.
 */

import { readFile, writeFile, mkdir, appendFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..");
const OUT_DIR = resolve(REPO_ROOT, "../FWM_Data/reddit_harvest");
const POSTS_PATH = resolve(OUT_DIR, "posts.ndjson");
const STATE_PATH = resolve(OUT_DIR, "_state/seen_ids.json");
const RUNS_DIR = resolve(OUT_DIR, "runs");

// A descriptive UA is the single most important politeness signal to Reddit.
const USER_AGENT =
  process.env.REDDIT_USER_AGENT ||
  "FWM-research-rss/0.1 (file-first measurement harvester; contact via repo)";

/**
 * Rotation list — researched 2026-06-22. `tier: "high"` = people routinely post
 * measurements AND/OR full-body photos with a fit/clothing-help intent.
 * Smaller niche subs are marked `verify: true` (third-party stats lag; the
 * harvester logs any that return no feed so you can prune them).
 */
const SUBREDDITS = [
  // --- top tier: dense measurements + photos + fit-help intent ---
  { name: "ABraThatFits", tier: "high" },        // measurements effectively required
  { name: "PetiteFashionAdvice", tier: "high" }, // height + measurements near-universal
  { name: "femalefashionadvice", tier: "high" }, // rules push size/budget/location
  { name: "Kibbe", tier: "high" },               // full-body photos + B/W/H to type
  { name: "bigboobproblems", tier: "high" },     // bust measurements + clothing/swim fit
  { name: "PlusSizeFashion", tier: "high" },
  { name: "PlusSize", tier: "high" },
  { name: "smallboobproblems", tier: "high" },
  { name: "TallFashionAdvice", tier: "high" },
  { name: "fashionadvice", tier: "high" },       // small, high signal
  { name: "maternityfashion", tier: "high", verify: true },
  // --- medium tier: good volume, measurements lighter or photo-led ---
  { name: "tall", tier: "medium" },
  { name: "TallGirls", tier: "medium" },
  { name: "BabyBumps", tier: "medium" },
  { name: "EnbyFashionAdvice", tier: "medium" },
  { name: "malefashionadvice", tier: "medium" },
  { name: "FashionPlus", tier: "medium", verify: true },
  { name: "OUTFITS", tier: "medium" },
  { name: "denim", tier: "medium" },
  // --- secondary / item-match tier (lower value for body data) ---
  { name: "findfashion", tier: "low" },
  { name: "HelpMeFind", tier: "low" },
  // NOTE: r/curvy and r/petite were REMOVED — despite the names, both are
  // overwhelmingly NSFW/solicitation subs (~95% of posts), not fashion advice.
  // The fashion equivalents are PetiteFashionAdvice / PlusSizeFashion / curvy-
  // fashion-flaired threads in FFA. Do NOT re-add the bare names.
];

// ---- CLI args -------------------------------------------------------------
const args = new Map(
  process.argv.slice(2).map((a) => {
    const m = a.match(/^--([^=]+)(?:=(.*))?$/);
    return m ? [m[1], m[2] ?? true] : [a, true];
  })
);
const LIMIT = Number(args.get("limit") || 100);
const DELAY_MS = Number(args.get("delay-ms") || 2500);
const VERIFY_IMAGES = !args.has("no-verify-images");
const DRY_RUN = args.has("dry-run");
const TIER_FILTER = args.get("tier"); // "high" | "medium" | "low"
const SUBS_OVERRIDE = args.get("subs"); // comma list

let subList = SUBREDDITS;
if (typeof SUBS_OVERRIDE === "string") {
  subList = SUBS_OVERRIDE.split(",")
    .map((s) => s.trim().replace(/^r\//i, ""))
    .filter(Boolean)
    .map((name) => ({ name, tier: "manual" }));
} else if (typeof TIER_FILTER === "string") {
  subList = SUBREDDITS.filter((s) => s.tier === TIER_FILTER);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- Atom parsing (no XML dep; reddit's feed is consistent) ----------------
function decodeEntities(s) {
  return s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#x27;/g, "'")
    .replace(/&#x2F;/g, "/")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&"); // amp last
}
const stripTags = (html) => decodeEntities(html.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
const tag = (block, name) => {
  const m = block.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`, "i"));
  return m ? m[1].trim() : "";
};

function parseFeed(xml) {
  const entries = [];
  const re = /<entry>([\s\S]*?)<\/entry>/g;
  let m;
  while ((m = re.exec(xml))) {
    const b = m[1];
    const linkM = b.match(/<link[^>]*href="([^"]+)"/i);
    entries.push({
      id: tag(b, "id"), // reddit fullname, e.g. t3_1uc2nw9
      title: decodeEntities(tag(b, "title")),
      author: stripTags(tag(b, "author")),
      published: tag(b, "published"),
      updated: tag(b, "updated"),
      category: (b.match(/<category[^>]*term="([^"]+)"/i) || [])[1] || "",
      permalink: linkM ? linkM[1] : "",
      contentHtml: decodeEntities(tag(b, "content")),
    });
  }
  return entries;
}

// ---- measurement extraction (heuristic; raw matches kept for review) -------
// Plausible INCH ranges per field. A parsed value outside its range is almost
// always a misparse (a cm value read as inches, or an unrelated number) and is
// dropped rather than stored. These also turn "70 cm waist" into a sane 28".
const INCH_BOUNDS = {
  height_in: [48, 84],
  bust_in: [26, 65],
  chest_in: [26, 65],
  waist_in: [18, 60],
  hips_in: [25, 75],
  inseam_in: [22, 42],
};
const WEIGHT_BOUNDS = [70, 500]; // lbs; below ~70 is almost never an adult's own weight

const inRange = (key, n) => {
  const b = INCH_BOUNDS[key];
  return b ? n >= b[0] && n <= b[1] : true;
};
// Convert a captured number + optional unit token to inches (cm -> in).
const toInches = (numStr, unit) => {
  let n = Number(numStr);
  if (unit && /cm|cent/i.test(unit)) n = n / 2.54;
  return Math.round(n);
};

function extractMeasurements(text) {
  const out = { raw: [] };
  // Only store a value once, and only if it passes the plausibility bound.
  const push = (key, val, rawStr) => {
    if (out[key] !== undefined) return;
    if (!inRange(key, val)) return;
    out[key] = val;
    out.raw.push(rawStr);
  };
  let m;

  // height: 5'1", 5 ft 1, 5'1, 160cm
  if ((m = text.match(/\b([4-6])\s*['’′]\s*(\d{1,2})\s*(?:["”″]|''|in\b)?/))) {
    push("height_in", Number(m[1]) * 12 + Number(m[2]), m[0].trim());
  } else if ((m = text.match(/\b([4-6])\s*(?:ft|feet)\.?\s*(\d{1,2})\b/i))) {
    push("height_in", Number(m[1]) * 12 + Number(m[2]), m[0].trim());
  } else if ((m = text.match(/\b(1[4-9]\d|2[0-1]\d)\s*cm\b/i))) {
    push("height_in", Math.round(Number(m[1]) / 2.54), m[0].trim());
  }

  if ((m = text.match(/\b(\d{2,3})\s*(?:lbs?|pounds)\b/i))) {
    const n = Number(m[1]);
    if (n >= WEIGHT_BOUNDS[0] && n <= WEIGHT_BOUNDS[1]) push("weight_lbs", n, m[0].trim());
  } else if ((m = text.match(/\b(\d{2,3})\s*(?:kg|kilos?)\b/i))) {
    const n = Math.round(Number(m[1]) * 2.205);
    if (n >= WEIGHT_BOUNDS[0] && n <= WEIGHT_BOUNDS[1]) push("weight_lbs", n, m[0].trim());
  }

  // bra size: band 26-48 + cup letters (e.g. 32DD, 34 B). This is the most
  // false-positive-prone pattern — a lone band number + single letter also
  // matches age/gender tags ("28F"), pronouns ("F 28 I need…" -> "28I"), and
  // stray words. Rules: a multi-letter cup (DD, HH, …) is unambiguous on its
  // own; a single-letter cup, or any space between band and cup, only counts
  // inside real bra context (the words bra/cup/band/underbust nearby). Also
  // guard temperature grades ("36C weather"). Scan all matches, take first valid.
  {
    // bra/bust context lets a single-letter cup ("32d") count while blocking age
    // tags ("28F") in non-bra posts. Cup match is case-insensitive (people write
    // "32d"), normalized to uppercase.
    const braCtx = /\b(bras?|cups?|band|under\s?bust|sister size|boobs?|breasts?|bust)\b/i.test(text);
    const braRe = /\b(2[68]|3[0-9]|4[0-8])(\s?)([A-Ka-k]{1,3})\b(?!\s*(?:weather|degree|deg\b|celsius|fahrenheit|°|temp))/g;
    for (const mm of text.matchAll(braRe)) {
      const band = mm[1];
      const gap = mm[2];
      const cup = mm[3].toUpperCase();
      const multiCup = cup.length >= 2;
      // Multi-letter cup (DD, HH…) is unambiguous when contiguous; if there's a
      // space it needs context. A single-letter cup needs context when contiguous
      // and is rejected when spaced (almost always a pronoun/word: "28 I", "30 A").
      const ok = multiCup ? (gap ? braCtx : true) : gap ? false : braCtx;
      if (ok) {
        push("bra_size", `${band}${cup}`, mm[0].trim());
        break;
      }
    }
  }

  for (const [key, label] of [
    ["bust_in", "bust"],
    ["chest_in", "chest"],
    ["waist_in", "waist"],
    ["hips_in", "hips?"],
    ["inseam_in", "inseam"],
  ]) {
    const k = key === "hips_in" ? "hips_in" : key;
    // "waist 27", "waist: 27", "waist is about 27", "27 inch waist", "27cm waist".
    // Capture the trailing/leading unit so cm can be converted to inches; values
    // that land outside the field's plausible inch range are rejected by push().
    const r1 = new RegExp(`\\b${label}\\b(?:\\s*(?:is|are|of|about|around|approx\\.?|roughly|~|:|=|-)){0,3}\\s*["”″]?(\\d{2,3}(?:\\.\\d)?)\\s*(cm|centimet\\w*|in\\b|inch\\w*|["”″])?`, "i");
    const r2 = new RegExp(`\\b(\\d{2,3}(?:\\.\\d)?)\\s*(cm|centimet\\w*|in\\b|inch\\w*|["”″])?\\s*${label}\\b`, "i");
    if ((m = text.match(r1)) || (m = text.match(r2))) {
      push(k, toInches(m[1], m[2]), m[0].trim());
    }
  }
  return out;
}

function hasAnyMeasurement(meas) {
  return Object.keys(meas).some((k) => k !== "raw" && meas[k] !== undefined);
}

// Drop posts that aren't genuine fit/clothing-help requests: NSFW solicitation,
// "rate me" karma posts, content selling. The bare-name body subs (r/curvy,
// r/petite) are removed at the source above; this is the secondary defense for
// stray NSFW posts that leak into otherwise-SFW subs. Tuned against real
// harvested titles. Word-boundaried so fashion terms ("pencil skirt", "classy",
// "bodycon") are NOT caught.
const OFF_INTENT_RE = new RegExp(
  "\\b(" +
    // explicit sexual / anatomy
    "dtf|nsfw|onlyfans|only fans|fuck\\w*|cock|dick|pussy|tits|titties|titty|funbags|" +
    "cum\\w*|horny|slut|sluts?|whore|nude|nudes|naked|boobies|booty|thicc|" +
    "blowjob|deepthroat|creampie|squirt|moan\\w*|" +
    // breeding/solicitation phrasing seen in the data
    "breed|breeding|bred|drain (?:you|me)|sit on your face|eat my|lick my|" +
    "made for (?:fucking|breeding|sex)|built to be|here'?s your dinner|" +
    // hookup / selling / karma-bait
    "hook ?up|f4[mfa]|m4[mfa]|sext|cashapp|venmo me|selling (?:my )?(?:content|pics|nudes)|" +
    "rate me|am i (?:hot|sexy|attractive|fuckable|too small)|would you (?:hit it|risk|smash)|" +
    "fuckable|do you (?:like it|want to)" +
  ")\\b",
  "i"
);
function looksOffIntent(text) {
  return OFF_INTENT_RE.test(text);
}

// ---- image extraction ------------------------------------------------------
const IMG_HOSTS = /(?:i\.redd\.it|preview\.redd\.it|external-preview\.redd\.it|i\.imgur\.com|imgur\.com)\/[^\s"'<>)]+/gi;
const IMG_EXT = /https?:\/\/[^\s"'<>)]+\.(?:jpe?g|png|webp|gif)(?:\?[^\s"'<>)]*)?/gi;
function extractImageUrls(html) {
  const urls = new Set();
  for (const re of [IMG_HOSTS, IMG_EXT]) {
    let m;
    while ((m = re.exec(html))) {
      let u = m[0].replace(/&amp;/g, "&");
      if (!/^https?:/i.test(u)) u = "https://" + u;
      // skip reddit award/icon/static junk
      if (/redditstatic|awardName|icon\.png|emoji/i.test(u)) continue;
      urls.add(u);
    }
  }
  return [...urls];
}

// posts authored by the sub itself or matching megathread patterns are noise
const MEGATHREAD_RE = /\b(mini wins|daily|weekly|monthly|megathread|discussion thread|simple questions?|moronic|free[-\s]?talk|psa|mod\s?post|sticky|rules?)\b/i;
function isNoise(entry, subName) {
  const a = entry.author.toLowerCase();
  if (a === `/u/${subName}`.toLowerCase()) return true;
  if (/automoderator/i.test(a)) return true;
  if (MEGATHREAD_RE.test(entry.title)) return true;
  return false;
}

async function fetchFeed(subName) {
  const url = `https://www.reddit.com/r/${subName}/new/.rss?limit=${LIMIT}`;
  for (let attempt = 0; attempt < 4; attempt++) {
    let res;
    try {
      res = await fetch(url, { headers: { "User-Agent": USER_AGENT, Accept: "application/atom+xml" } });
    } catch (e) {
      await sleep(1500 * (attempt + 1));
      continue;
    }
    if (res.status === 429) {
      const reset = Number(res.headers.get("x-ratelimit-reset") || 60);
      const wait = Math.min(120, reset + 1) * 1000;
      console.warn(`   429 on r/${subName} — backing off ${Math.round(wait / 1000)}s`);
      await sleep(wait);
      continue;
    }
    if (!res.ok) return { ok: false, status: res.status, xml: "" };
    const xml = await res.text();
    return { ok: true, status: res.status, xml };
  }
  return { ok: false, status: 0, xml: "" };
}

async function verifyImage(url) {
  try {
    let res = await fetch(url, { method: "HEAD", headers: { "User-Agent": USER_AGENT }, redirect: "follow" });
    // some hosts (preview.redd.it) reject HEAD; fall back to a ranged GET
    if (res.status === 403 || res.status === 405) {
      res = await fetch(url, { headers: { "User-Agent": USER_AGENT, Range: "bytes=0-0" }, redirect: "follow" });
    }
    return res.status;
  } catch {
    return 0;
  }
}

async function loadSeen() {
  if (!existsSync(STATE_PATH)) return new Set();
  try {
    return new Set(JSON.parse(await readFile(STATE_PATH, "utf8")));
  } catch {
    return new Set();
  }
}

async function main() {
  await mkdir(resolve(OUT_DIR, "_state"), { recursive: true });
  await mkdir(RUNS_DIR, { recursive: true });

  const seen = await loadSeen();
  const startedAt = new Date().toISOString();
  const kept = [];
  const perSub = [];

  console.log(`Harvesting ${subList.length} subreddit(s) → ${POSTS_PATH}`);
  console.log(`UA: ${USER_AGENT}\n`);

  for (const sub of subList) {
    const { ok, status, xml } = await fetchFeed(sub.name);
    if (!ok || !xml) {
      console.warn(`r/${sub.name}: feed unavailable (HTTP ${status})${sub.verify ? " [verify: may be dead/private]" : ""}`);
      perSub.push({ subreddit: sub.name, status, entries: 0, kept: 0, error: true });
      await sleep(DELAY_MS);
      continue;
    }
    const entries = parseFeed(xml);
    let keptHere = 0;
    for (const e of entries) {
      if (!e.id || seen.has(e.id)) continue;
      seen.add(e.id);
      if (isNoise(e, sub.name)) continue;

      const text = `${e.title}\n${stripTags(e.contentHtml)}`;
      if (looksOffIntent(text)) continue;
      const measurements = extractMeasurements(text);
      const imageUrls = extractImageUrls(e.contentHtml);
      const hasMeas = hasAnyMeasurement(measurements);
      if (!hasMeas && imageUrls.length === 0) continue;

      let images = imageUrls.map((url) => ({ url, status: null }));
      if (VERIFY_IMAGES && images.length) {
        for (const img of images) img.status = await verifyImage(img.url);
      }

      kept.push({
        id: e.id,
        subreddit: sub.name,
        tier: sub.tier,
        title: e.title,
        author: e.author,
        permalink: e.permalink,
        created_utc: e.published,
        // The Atom feed's <category> is ALWAYS the subreddit, never the post's
        // link flair — so flair is null here and backfilled by
        // scripts/enrich-reddit-flair.mjs (old.reddit HTML, the only free source).
        flair: null,
        has_measurements: hasMeas,
        measurements: hasMeas ? measurements : null,
        image_urls: images,
        image_ok_count: images.filter((i) => i.status && i.status >= 200 && i.status < 300).length,
        raw_text: stripTags(e.contentHtml).slice(0, 2000),
        harvested_at: startedAt,
        source: "reddit_rss_new",
      });
      keptHere++;
    }
    console.log(
      `r/${sub.name}: ${entries.length} posts, kept ${keptHere} (measurements and/or images)`
    );
    perSub.push({ subreddit: sub.name, status, entries: entries.length, kept: keptHere });
    await sleep(DELAY_MS);
  }

  // ---- write ----
  const withMeas = kept.filter((k) => k.has_measurements).length;
  const withImg = kept.filter((k) => k.image_urls.length).length;
  const summary = {
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    subreddits: subList.map((s) => s.name),
    new_records: kept.length,
    with_measurements: withMeas,
    with_images: withImg,
    per_subreddit: perSub,
    dry_run: DRY_RUN,
  };

  if (!DRY_RUN) {
    if (kept.length) {
      await appendFile(POSTS_PATH, kept.map((k) => JSON.stringify(k)).join("\n") + "\n", "utf8");
    }
    await writeFile(STATE_PATH, JSON.stringify([...seen]), "utf8");
    await writeFile(
      resolve(RUNS_DIR, `run_${startedAt.replace(/[:.]/g, "-")}.json`),
      JSON.stringify(summary, null, 2),
      "utf8"
    );
  }

  console.log(
    `\n${DRY_RUN ? "[DRY RUN] " : ""}New records: ${kept.length}  ` +
      `(with measurements: ${withMeas}, with images: ${withImg})`
  );
  if (!DRY_RUN) console.log(`Appended to ${POSTS_PATH}`);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}

export { extractMeasurements, extractImageUrls, parseFeed, isNoise, looksOffIntent };
