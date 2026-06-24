#!/usr/bin/env node
/**
 * Backfill the real link flair for harvested Reddit posts.
 *
 * WHY a separate step: the Atom RSS feed used by the harvester does NOT expose
 * link flair (its <category> is always just the subreddit), and the www `.json`
 * endpoints return 403. The only free source is the old.reddit.com HTML page,
 * which serves a `<span class="linkflairlabel" title="…">` per post. That's one
 * extra HTTP request per post, so it's kept out of the fast harvest loop and run
 * as a paced, resumable batch here.
 *
 * Input/Output: FWM_Data/reddit_harvest/posts.ndjson (updated in place — each
 *   record's `flair` is set to the real flair string, or "" if the post has none).
 * State: FWM_Data/reddit_harvest/_state/flair.json  { "<id>": "<flair>" } so a
 *   re-run skips already-resolved posts.
 *
 * Writes NOTHING to Supabase.
 *
 * Usage:
 *   node scripts/enrich-reddit-flair.mjs                 # all posts missing flair
 *   node scripts/enrich-reddit-flair.mjs --only-measured # just measured posts first
 *   node scripts/enrich-reddit-flair.mjs --limit=200 --delay-ms=2000
 */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIR = resolve(__dirname, "../../FWM_Data/reddit_harvest");
const POSTS = resolve(DIR, "posts.ndjson");
const STATE = resolve(DIR, "_state/flair.json");

const args = new Map(process.argv.slice(2).map((a) => {
  const [k, v] = a.replace(/^--/, "").split("=");
  return [k, v ?? true];
}));
const DELAY_MS = Number(args.get("delay-ms") || 2000);
const LIMIT = args.has("limit") ? Number(args.get("limit")) : Infinity;
const ONLY_MEASURED = args.has("only-measured");

const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function decode(s) {
  return s.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#32;/g, " ").replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"').trim();
}

// Extract link flair from an old.reddit post page. Prefer the title attribute of
// the linkflairlabel span; fall back to its inner text. Returns "" when the post
// has no flair (the span is absent).
function parseFlair(htmlText) {
  // The flair span's class contains "linkflairlabel" but is NOT first
  // (e.g. class="flairrichtext flaircolordark linkflairlabel "), and its title
  // attribute may hold &quot;/&#39; entities. Match the span anywhere and prefer
  // the title attribute, falling back to the inner text.
  let m = htmlText.match(/<span[^>]*\blinkflairlabel\b[^>]*\btitle="([^"]*)"/i);
  if (m && m[1].trim()) return decode(m[1]);
  m = htmlText.match(/\blinkflairlabel\b[^>]*>(?:\s*<span>)?([^<]+)</i);
  return m ? decode(m[1]) : "";
}

async function fetchFlair(permalink) {
  const url = permalink.replace("://www.reddit.com", "://old.reddit.com");
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const res = await fetch(url, { headers: { "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9" }, redirect: "follow" });
      if (res.status === 429 || res.status === 503) {
        await sleep(DELAY_MS * (attempt + 2));
        continue;
      }
      if (!res.ok) return { ok: false, status: res.status };
      const text = await res.text();
      return { ok: true, flair: parseFlair(text) };
    } catch {
      await sleep(DELAY_MS * (attempt + 1));
    }
  }
  return { ok: false, status: "error" };
}

async function main() {
  const rows = (await readFile(POSTS, "utf8")).split("\n").filter(Boolean).map((l) => JSON.parse(l));
  let state = {};
  try { state = JSON.parse(await readFile(STATE, "utf8")); } catch {}

  // Posts still needing flair: not resolved in state, and currently missing OR
  // carrying the old bogus value (early harvests stored the subreddit name as
  // "flair" before that bug was fixed — treat that as missing).
  const needsFlair = (r) =>
    r.flair === null ||
    r.flair === undefined ||
    (typeof r.flair === "string" && r.flair.toLowerCase() === r.subreddit.toLowerCase());
  let todo = rows.filter((r) => state[r.id] === undefined && needsFlair(r));
  if (ONLY_MEASURED) todo = todo.filter((r) => r.has_measurements);
  todo = todo.slice(0, LIMIT);

  console.log(`${rows.length} posts total; ${todo.length} to fetch this run (delay ${DELAY_MS}ms, ${ONLY_MEASURED ? "measured-only" : "all"})`);

  let done = 0, failed = 0;
  for (const r of todo) {
    const out = await fetchFlair(r.permalink);
    if (out.ok) { state[r.id] = out.flair; done++; }
    else { failed++; }
    if ((done + failed) % 25 === 0) {
      await mkdir(dirname(STATE), { recursive: true });
      await writeFile(STATE, JSON.stringify(state), "utf8");
      console.log(`  …${done + failed}/${todo.length} (${done} ok, ${failed} failed)`);
    }
    await sleep(DELAY_MS);
  }

  // Apply resolved flairs back onto every row and rewrite both files.
  for (const r of rows) if (state[r.id] !== undefined) r.flair = state[r.id];
  await mkdir(dirname(STATE), { recursive: true });
  await writeFile(STATE, JSON.stringify(state), "utf8");
  await writeFile(POSTS, rows.map((r) => JSON.stringify(r)).join("\n") + "\n", "utf8");

  const withFlair = rows.filter((r) => r.flair).length;
  console.log(`\nDone: ${done} fetched, ${failed} failed. ${withFlair}/${rows.length} posts now have a flair string.`);
  console.log(`Re-run to continue the rest. (nothing written to Supabase)`);
}

main().catch((e) => { console.error(e); process.exit(1); });
