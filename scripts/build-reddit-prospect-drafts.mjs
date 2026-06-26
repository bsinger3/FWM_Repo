#!/usr/bin/env node
/**
 * Score harvested Reddit posts as manual outreach prospects, run read-only dev
 * measurement searches, and draft reply copy for human review.
 *
 * Output:
 *   ../FWM_Data/_reports/reddit_prospect_drafts_<timestamp>.json
 *   ../FWM_Data/_reports/reddit_prospect_drafts_<timestamp>.md
 *
 * This does not contact Reddit, write Supabase, or send anything.
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertApprovedDevSupabase,
  callSupabaseRest,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const dataRoot = fwmDataDir(repoRoot);
const redditPath = path.join(dataRoot, "reddit_harvest", "posts_clean.ndjson");
const reportsDir = path.join(dataRoot, "_reports");

const args = new Map(
  process.argv.slice(2).map((arg) => {
    const [key, ...rest] = arg.replace(/^--/, "").split("=");
    return [key, rest.length ? rest.join("=") : "true"];
  }),
);
const limit = Math.max(1, Number(args.get("limit") || 25));
const searchLimit = Math.max(1, Number(args.get("search-limit") || 36));
const minScore = Number(args.get("min-score") || 7);
const siteBase = String(args.get("site-base") || "https://www.friendswithmeasurements.com/").replace(/\?$/, "");

const shoppingIntent = /\b(where (can|do|should)|recommend|recommendations?|suggestions?|looking for|help me find|need (a|an|some|new)|any brands?|brands?|stores?|retailers?|buy|shopping|hunt|ISO|in search of|dupes?|alternatives?)\b/i;
const garmentIntent = /\b(jeans?|pants|trousers|shorts?|skirts?|dresses?|bras?|sports bras?|tops?|shirts?|blouses?|sweaters?|jackets?|blazers?|swim|bikini|one[- ]piece|leggings?|business casual|workwear|formal|wedding|black tie)\b/i;
const lowOutreachIntent = /\b(which .* look|does this .* look|fit check|outfit check|rate|aesthetic|do these fit|how do these|alterations?|tailor|tailoring)\b/i;
const notARequestIntent = /(\[review\]|review\]|for the win|haul|what i wore|outfit of the day)/i;
const measurementCheckIntent = /\bmeasurement check\b/i;
const metaIntent = /\b(pro tips|daily thread|weekly thread|megathread|discussion thread)\b/i;

const clothingTypeHints = [
  ["swimwear", /\b(swim|swimsuits?|bikini|one[- ]piece|tankini)\b/i],
  ["pants", /\b(pants|trousers|slacks|linen pants|work pants|business casual)\b/i],
  ["jeans", /\bjeans?|denim\b/i],
  ["shorts", /\bshorts?\b/i],
  ["skirt", /\b(skirts?|skorts?)\b/i],
  ["dress", /\b(dresses?|gown|black tie|formal|wedding guest)\b/i],
  ["bra", /\b(bras?|sports bras?|strapless|bralette|full bust|cups?|band)\b/i],
  ["tops", /\b(tops?|shirts?|blouses?|tees?|t-shirts?|tank tops?|sweaters?)\b/i],
  ["outerwear", /\b(jackets?|blazers?|coats?)\b/i],
  ["leggings", /\bleggings?\b/i],
];

function readNdjson(text) {
  return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

function nMeasurements(m) {
  return Object.keys(m || {}).filter((k) => k !== "raw").length;
}

function splitBraSize(value) {
  const match = String(value || "").trim().match(/^(\d{2})([A-Z]+)$/i);
  return match ? { band: Number(match[1]), cup: match[2].toUpperCase() } : null;
}

function heightParts(heightIn) {
  if (!Number.isFinite(Number(heightIn))) return null;
  const total = Number(heightIn);
  return { feet: Math.floor(total / 12), inches: total % 12 };
}

function inferClothingType(post) {
  const haystack = `${post.title || ""}\n${post.raw_text || ""}\n${(post.clothing_request || []).join(" ")}`;
  for (const [type, pattern] of clothingTypeHints) {
    if (pattern.test(haystack)) return type;
  }
  return null;
}

function scorePost(post) {
  const m = post.measurements || {};
  const text = `${post.title || ""}\n${post.raw_text || ""}`;
  const imageCount = (post.image_urls || []).length;
  const okImageCount = Number(post.image_ok_count || 0);
  const fields = nMeasurements(m);
  let score = 0;
  const reasons = [];

  if (!post.has_measurements || !fields) return { score: -999, reasons: ["no parsed measurements"] };
  if (metaIntent.test(text)) return { score: -999, reasons: ["meta thread"] };
  if (notARequestIntent.test(text)) return { score: -999, reasons: ["review/showcase, not a request"] };
  if (measurementCheckIntent.test(text)) return { score: -999, reasons: ["measurement check"] };
  if (lowOutreachIntent.test(text)) return { score: -999, reasons: ["style/fit feedback"] };
  score += 2 + fields;
  reasons.push(`${fields} parsed measurement${fields === 1 ? "" : "s"}`);

  if (m.height_in) { score += 1; reasons.push("height present"); }
  if (m.weight_lbs) score += 0.5;
  if (m.bra_size) { score += 2; reasons.push("bra size present"); }
  if (m.bust_in || m.waist_in || m.hips_in || m.inseam_in) {
    score += 1.5;
    reasons.push("specific body dimension present");
  }
  if ((m.waist_in && m.hips_in) || (m.bust_in && m.waist_in) || (m.height_in && m.inseam_in)) {
    score += 1.5;
    reasons.push("strong fit-pair");
  }
  if (imageCount) {
    score += Math.min(2, imageCount * 0.5);
    reasons.push(`${imageCount} image${imageCount === 1 ? "" : "s"}`);
  }
  if (okImageCount) score += 0.5;
  if (shoppingIntent.test(text)) {
    score += 3;
    reasons.push("explicit shopping/recommendation intent");
  }
  if (garmentIntent.test(text)) {
    score += 1;
    reasons.push("garment-specific request");
  }
  if (lowOutreachIntent.test(text)) {
    score -= 2;
    reasons.push("more style/fit feedback than shopping");
  }
  if (notARequestIntent.test(text)) {
    score -= 6;
    reasons.push("appears to be a review/showcase, not a request");
  }
  if (measurementCheckIntent.test(text) && !shoppingIntent.test(text)) {
    score -= 3;
    reasons.push("measurement check without shopping request");
  }
  if (metaIntent.test(text)) {
    score -= 10;
    reasons.push("meta thread");
  }
  if (post.tier === "high") score += 0.5;

  return { score: Number(score.toFixed(1)), reasons };
}

function buildSearchBody(post, clothingTypeId = null) {
  const m = post.measurements || {};
  const bra = splitBraSize(m.bra_size);
  return {
    in_clothing_type_id: clothingTypeId,
    in_height: m.height_in || null,
    in_hips: m.hips_in || null,
    in_weight: m.weight_lbs || null,
    in_bust: m.bust_in || (bra ? bra.band : null),
    in_cup_size: bra ? bra.cup : null,
    in_waist: m.waist_in || null,
    require_height: Boolean(m.height_in),
    require_hips: Boolean(m.hips_in),
    require_weight: false,
    require_bust: Boolean(m.bust_in || bra),
    require_waist: Boolean(m.waist_in),
    limit_n: searchLimit,
    offset_n: 0,
  };
}

function buildPrefillUrl(post) {
  const m = post.measurements || {};
  const params = new URLSearchParams();
  const h = heightParts(m.height_in);
  if (h) {
    params.set("h_ft", String(h.feet));
    params.set("h_in", String(h.inches));
  }
  if (m.weight_lbs) params.set("weight", String(Math.round(m.weight_lbs)));
  if (m.bust_in) params.set("bust", String(Math.round(m.bust_in)));
  if (m.bra_size) {
    const bra = splitBraSize(m.bra_size);
    if (bra) {
      params.set("bust", String(bra.band));
      params.set("cup", bra.cup);
    }
  }
  if (m.waist_in) params.set("waist", String(Math.round(m.waist_in)));
  if (m.hips_in) params.set("hips", String(Math.round(m.hips_in)));
  const req = [];
  if (m.height_in) req.push("height");
  if (m.bust_in || m.bra_size) req.push("bust");
  if (m.waist_in) req.push("waist");
  if (m.hips_in) req.push("hips");
  if (req.length) params.set("req", req.join(","));
  params.set("utm_source", "reddit");
  params.set("utm_medium", "manual_reply");
  params.set("utm_campaign", "reddit_measurement_prospecting");
  params.set("utm_content", post.id);
  return `${siteBase}${siteBase.includes("?") ? "&" : "?"}${params.toString()}`;
}

function measurementSummary(m = {}) {
  const parts = [];
  if (m.height_in) {
    const h = heightParts(m.height_in);
    parts.push(`${h.feet}'${h.inches}"`);
  }
  if (m.weight_lbs) parts.push(`${Math.round(m.weight_lbs)} lb`);
  if (m.bra_size) parts.push(`${m.bra_size} bra`);
  if (m.bust_in) parts.push(`${Math.round(m.bust_in)}" bust`);
  if (m.waist_in) parts.push(`${Math.round(m.waist_in)}" waist`);
  if (m.hips_in) parts.push(`${Math.round(m.hips_in)}" hips`);
  if (m.inseam_in) parts.push(`${Math.round(m.inseam_in)}" inseam`);
  return parts.join(", ");
}

function groupBrands(matches) {
  const byBrand = new Map();
  for (const row of matches || []) {
    const brand = cleanBrand(row.brand || row.source_site_display);
    if (!brand || brand === "Unknown") continue;
    const current = byBrand.get(brand) || {
      brand,
      count: 0,
      product_urls: [],
      source_sites: new Set(),
      sizes: new Set(),
      sample_image_url: null,
    };
    current.count += 1;
    if (row.product_page_url_display && current.product_urls.length < 3) current.product_urls.push(row.product_page_url_display);
    if (row.source_site_display) current.source_sites.add(row.source_site_display);
    if (row.size_display) current.sizes.add(row.size_display);
    if (!current.sample_image_url && row.original_url_display) current.sample_image_url = row.original_url_display;
    byBrand.set(brand, current);
  }
  return [...byBrand.values()]
    .sort((a, b) => b.count - a.count || a.brand.localeCompare(b.brand))
    .slice(0, 6)
    .map((b) => ({
      ...b,
      source_sites: [...b.source_sites],
      sizes: [...b.sizes].slice(0, 5),
    }));
}

function cleanBrand(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const host = new URL(raw).hostname.replace(/^www\./, "");
    if (host === "amazon.com") return "Amazon";
    if (host === "shopcider.com") return "Cider";
    return host.split(".").slice(0, -1).join(".") || host;
  } catch {
    return raw;
  }
}

function draftReply(post, brands, prefillUrl, searchStrategy) {
  const brandNames = brands.slice(0, 4).map((b) => b.brand);
  const clothes = inferClothingType(post);
  const categoryText = clothes && searchStrategy === "strict"
    ? `${clothes.replace(/_/g, " ")} options`
    : "similar-measurement examples";
  const brandSentence = brandNames.length
    ? `A few brands that came up with ${categoryText} near your measurements: ${brandNames.join(", ")}.`
    : `I did not find enough brand-specific matches to name confidently, but the measurement search link should still be useful.`;
  return [
    `I ran your measurements (${measurementSummary(post.measurements)}) through Friends with Measurements, which searches real fit photos from shoppers with similar measurements.`,
    brandSentence,
    `Here is the prefilled search: ${prefillUrl}`,
    `I would still double-check size charts/reviews before buying, but this may give you a more measurement-based starting point than guessing from model photos.`,
  ].join("\n\n");
}

function permalink(post) {
  const value = String(post.permalink || "");
  if (value.startsWith("http")) return value;
  return `https://www.reddit.com${value}`;
}

async function enrichProductPages(guard, matches) {
  const ids = [...new Set((matches || []).map((m) => m.product_page_id).filter(Boolean))];
  if (!ids.length) return new Map();
  try {
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "staging.product_pages",
      method: "GET",
      searchParams: {
        select: "id,product_title_raw,product_category_raw,mother_category_id,observed_clothing_type_ids,source_site,brand",
        id: `in.(${ids.join(",")})`,
      },
    });
    return new Map((data || []).map((row) => [row.id, row]));
  } catch (error) {
    if (!String(error?.message || error).includes("staging.product_pages")) throw error;
    return new Map();
  }
}

async function searchMatches(guard, initialBody, { allowDropCup = true } = {}) {
  const variants = [
    { label: "strict", body: { ...initialBody } },
    { label: "no_clothing_filter", body: { ...initialBody, in_clothing_type_id: null } },
    {
      label: "relaxed_requirements",
      body: {
        ...initialBody,
        in_clothing_type_id: null,
        require_height: false,
        require_hips: false,
        require_weight: false,
        require_bust: false,
        require_waist: false,
      },
    },
    allowDropCup ? {
      label: "relaxed_no_cup",
      body: {
        ...initialBody,
        in_clothing_type_id: null,
        in_cup_size: null,
        require_height: false,
        require_hips: false,
        require_weight: false,
        require_bust: false,
        require_waist: false,
      },
    } : null,
  ].filter(Boolean);

  let best = { label: "none", body: initialBody, matches: [] };
  for (const variant of variants) {
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "rpc/match_by_measurements",
      method: "POST",
      body: variant.body,
    });
    const matches = Array.isArray(data) ? data : [];
    const brands = groupBrands(matches);
    if (brands.length && matches.length >= 3) {
      return { label: variant.label, body: variant.body, matches };
    }
    if (matches.length > best.matches.length) {
      best = { label: variant.label, body: variant.body, matches };
    }
  }
  return best;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Reddit prospect search guard" });

  const posts = readNdjson(await readFile(redditPath, "utf8"));
  const scored = posts
    .map((post) => ({ post, ...scorePost(post), clothing_type_id: inferClothingType(post) }))
    .filter((item) => item.score >= minScore)
    .sort((a, b) => b.score - a.score || Date.parse(b.post.created_utc) - Date.parse(a.post.created_utc));

  const leads = [];

  for (const item of scored) {
    if (leads.length >= limit) break;
    const body = buildSearchBody(item.post, item.clothing_type_id);
    const search = await searchMatches(guard, body, { allowDropCup: item.clothing_type_id !== "bra" });
    const matches = search.matches;

    const pages = await enrichProductPages(guard, matches);
    const enrichedMatches = matches.map((match) => ({
      ...match,
      product_page: match.product_page_id ? pages.get(match.product_page_id) || null : null,
    }));
    const brands = groupBrands(enrichedMatches);
    if (!brands.length) continue;
    const prefillUrl = buildPrefillUrl(item.post);

    leads.push({
      id: item.post.id,
      subreddit: item.post.subreddit,
      title: item.post.title,
      permalink: permalink(item.post),
      author: item.post.author,
      created_utc: item.post.created_utc,
      score: item.score,
      score_reasons: item.reasons,
      outreach_quality: item.score >= 11 ? "high" : item.score >= 9 ? "medium" : "review",
      inferred_clothing_type_id: item.clothing_type_id,
      used_clothing_filter: Boolean(search.body.in_clothing_type_id),
      measurements: item.post.measurements,
      measurement_summary: measurementSummary(item.post.measurements),
      image_count: (item.post.image_urls || []).length,
      reddit_image_urls: (item.post.image_urls || []).map((img) => img.url || img),
      clothing_request: item.post.clothing_request || [],
      match_query_url: prefillUrl,
      search_strategy: search.label,
      search_body: search.body,
      match_count: enrichedMatches.length,
      brands,
      sample_matches: enrichedMatches.slice(0, 8).map((row) => ({
        brand: cleanBrand(row.brand || row.source_site_display),
        source_site_display: row.source_site_display,
        size_display: row.size_display,
        color_display: row.color_display,
        height_in_display: row.height_in_display,
        weight_display_display: row.weight_display_display,
        bust_in_number_display: row.bust_in_number_display,
        cupsize_display: row.cupsize_display,
        waist_in: row.waist_in,
        hips_in_display: row.hips_in_display,
        inseam_inches_display: row.inseam_inches_display,
        image_url: row.original_url_display,
        product_url: row.product_page_url_display,
        product_title_raw: row.product_page?.product_title_raw || null,
        mother_category_id: row.product_page?.mother_category_id || null,
        observed_clothing_type_ids: row.product_page?.observed_clothing_type_ids || [],
      })),
      draft_reply: draftReply(item.post, brands, prefillUrl, search.label),
      text_excerpt: String(item.post.raw_text || "").replace(/\s+/g, " ").slice(0, 500),
    });
  }

  const generatedAt = new Date().toISOString();
  const stamp = generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  await mkdir(reportsDir, { recursive: true });
  const jsonPath = path.join(reportsDir, `reddit_prospect_drafts_${stamp}.json`);
  const mdPath = path.join(reportsDir, `reddit_prospect_drafts_${stamp}.md`);

  const report = {
    generated_at: generatedAt,
    source_reddit_path: redditPath,
    supabase_project_ref: guard.projectRef,
    scoring: {
      total_posts: posts.length,
      measured_posts: posts.filter((p) => p.has_measurements).length,
      qualified_candidates: scored.length,
      selected_leads: leads.length,
      min_score: minScore,
    },
    leads,
  };

  const md = [
    `# Reddit Prospect Drafts`,
    ``,
    `Generated: ${generatedAt}`,
    `Source: \`${redditPath}\``,
    `Dev search project: \`${guard.projectRef}\``,
    ``,
    `Scored ${posts.length} harvested posts; ${posts.filter((p) => p.has_measurements).length} had measurements; ${scored.length} met score >= ${minScore}; drafted ${leads.length}.`,
    ``,
    ...leads.flatMap((lead, index) => [
      `## ${index + 1}. r/${lead.subreddit}: ${lead.title}`,
      ``,
      `- Score: ${lead.score} (${lead.outreach_quality})`,
      `- Reasons: ${lead.score_reasons.join("; ")}`,
      `- Measurements: ${lead.measurement_summary}`,
      `- Images: ${lead.image_count}`,
      `- Clothing filter: ${lead.inferred_clothing_type_id || "none"}; search strategy: ${lead.search_strategy}`,
      `- Reddit: ${lead.permalink}`,
      `- Prefilled FWM URL: ${lead.match_query_url}`,
      `- Brand hits: ${lead.brands.map((b) => `${b.brand} (${b.count})`).join(", ") || "none"}`,
      ``,
      `Post excerpt: ${lead.text_excerpt}`,
      ``,
      `Draft reply:`,
      ``,
      "```text",
      lead.draft_reply,
      "```",
      ``,
      `Top sample matches:`,
      ``,
      ...lead.sample_matches.slice(0, 5).map((m) => `- ${m.brand || "Unknown"} ${m.size_display || ""} ${m.color_display || ""} | ${m.product_title_raw || m.product_url || ""} | image: ${m.image_url || ""}`),
      ``,
    ]),
  ].join("\n");

  await writeFile(jsonPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(mdPath, md, "utf8");

  console.log(JSON.stringify({
    generated_at: generatedAt,
    jsonPath,
    mdPath,
    scoring: report.scoring,
    top_leads: leads.slice(0, 8).map((lead) => ({
      id: lead.id,
      subreddit: lead.subreddit,
      score: lead.score,
      title: lead.title,
      measurements: lead.measurement_summary,
      brands: lead.brands.slice(0, 4).map((b) => b.brand),
    })),
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
