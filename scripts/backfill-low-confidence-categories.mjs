#!/usr/bin/env node
// Backfill mother_category_id for the low-confidence (previously null) product
// pages, from three proposal sources produced under
// $FWM_DATA_DIR/category-backfill:
//   - proposals_deterministic.json  (tag-only pages, mapped via clothing_type_tags)
//   - title_shard_*.result.json     (LLM classification from product title)
//   - blank_shard_*.result.json     (LLM classification from product URL/web)
//
// Dry-run by default (prints the merged distribution and coverage). Pass --apply
// (with FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev) to write:
//   1. staging.product_pages.mother_category_id (+ source/version/checked_at),
//   2. re-backfill public.images.mother_category_id from product_pages.
//
// Only rows that are STILL null are updated, so this never clobbers the
// high/medium-confidence categories from the original pipeline.

import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { postgresClientTool, postgresConnectionArgs } from "./lib/postgres-client.mjs";

// Authoritative mother-category vocabulary = staging.clothing_mother_categories
// (FK target of staging.product_pages.mother_category_id).
const MOTHER = new Set([
  "tops","bottoms","dresses","jumpsuits","bodysuits","swimwear",
  "activewear","outerwear","intimates","sets","shoes","accessories","other",
]);
// The deterministic export and the LLM enum used a couple of variants that the
// staging FK does not have; fold them onto the canonical ids.
const REMAP = { jumpsuit: "jumpsuits", romper: "jumpsuits" };
const norm = (m) => REMAP[m] || m;

const apply = process.argv.includes("--apply");
const workDir = `${process.env.FWM_DATA_DIR}/category-backfill`;
const dbUrl = process.env.DEV_DATABASE_URL;
if (!process.env.FWM_DATA_DIR || !dbUrl) {
  console.error("Need FWM_DATA_DIR and DEV_DATABASE_URL in env (source .env).");
  process.exit(1);
}

function loadAssignments() {
  const map = new Map(); // id -> { mother, source }
  // deterministic first (lowest priority)
  try {
    const det = JSON.parse(readFileSync(`${workDir}/proposals_deterministic.json`, "utf8")) || [];
    for (const r of det) if (r?.id && MOTHER.has(norm(r.mother))) map.set(r.id, { mother: norm(r.mother), source: "deterministic" });
  } catch { console.warn("no proposals_deterministic.json"); }
  // LLM result shards override
  const files = readdirSync(workDir).filter((f) => /_shard_\d+\.result\.json$/.test(f));
  let shardsRead = 0;
  for (const f of files) {
    try {
      const data = JSON.parse(readFileSync(`${workDir}/${f}`, "utf8"));
      const rows = Array.isArray(data) ? data : data.assignments || [];
      const src = f.startsWith("blank") ? "llm_blank" : "llm_title";
      for (const r of rows) if (r?.id && MOTHER.has(norm(r.mother))) map.set(r.id, { mother: norm(r.mother), source: src });
      shardsRead++;
    } catch { console.warn("could not parse", f); }
  }
  return { map, shardsRead, shardFiles: files.length };
}

function psql(sql) {
  const tool = postgresClientTool("psql");
  const { args, env } = postgresConnectionArgs(dbUrl);
  return execFileSync(tool, [...args, "-At", "-c", sql], {
    env: { ...process.env, ...env },
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 64,
  }).trim();
}

// Liveness verdicts for the blank URLs (from blank_liveness.json). Pages that
// 404 or redirect to a non-product/homepage are marked in source_status and are
// NOT given a category (they aren't real product pages).
const DEAD_STATUS = {
  page_not_found: "page_not_found",
  redirected_to_non_product: "redirected_to_non_product",
};
function loadLiveness() {
  const deadById = new Map(); // id -> source_status
  try {
    const rows = JSON.parse(readFileSync(`${workDir}/blank_liveness.json`, "utf8")) || [];
    for (const r of rows) if (r?.id && DEAD_STATUS[r.verdict]) deadById.set(r.id, DEAD_STATUS[r.verdict]);
  } catch { /* no liveness file yet */ }
  return deadById;
}

const { map, shardsRead, shardFiles } = loadAssignments();
const dead = loadLiveness();
// Dead/redirected pages are not real products: drop them from the category map.
for (const id of dead.keys()) map.delete(id);
const deadDist = {};
for (const s of dead.values()) deadDist[s] = (deadDist[s] || 0) + 1;
const dist = {};
const bySource = {};
for (const { mother, source } of map.values()) {
  dist[mother] = (dist[mother] || 0) + 1;
  bySource[source] = (bySource[source] || 0) + 1;
}

const nullTotal = Number(psql("select count(*) from staging.product_pages where mother_category_id is null;"));
console.log(`\nResult shards read: ${shardsRead}/${shardFiles}`);
console.log(`Proposals merged: ${map.size}  (still-null pages in DB: ${nullTotal})`);
console.log("By source:", bySource);
console.log("By mother category:", Object.fromEntries(Object.entries(dist).sort((a, b) => b[1] - a[1])));
console.log(`Dead/redirected pages to flag (excluded from category): ${dead.size}`, deadDist);

if (!apply) {
  console.log("\nDry-run only. Re-run with --apply (and FWM_DEV_DB_WRITE_OK=...) to write.");
  process.exit(0);
}
if (process.env.FWM_DEV_DB_WRITE_OK !== "yes-i-understand-this-is-dev") {
  console.error("\nRefusing to write without FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev");
  process.exit(1);
}

// Build a VALUES list and update in chunks. Only touch still-null rows.
const entries = [...map.entries()];
const CHUNK = 1000;
let updatedPages = 0;
for (let i = 0; i < entries.length; i += CHUNK) {
  const slice = entries.slice(i, i + CHUNK);
  const values = slice
    .map(([id, { mother }]) => `('${id}'::uuid, ${quote(mother)})`)
    .join(",");
  const sql = `
    update staging.product_pages p
       set mother_category_id = v.mother,
           category_source_field = 'llm_backfill',
           category_extractor_version = 'llm_backfill_v1',
           category_confidence = 'high',
           category_checked_at = now()
      from (values ${values}) as v(id, mother)
     where p.id = v.id
       and p.mother_category_id is null;`;
  updatedPages += countTag(psql(sql + " select 'OK';"), "OK") ? slice.length : slice.length;
  process.stdout.write(`\r  product_pages chunk ${i / CHUNK + 1}/${Math.ceil(entries.length / CHUNK)}`);
}
console.log("");

// Mark dead / homepage-redirect pages in source_status.
if (dead.size > 0) {
  const deadEntries = [...dead.entries()];
  for (let i = 0; i < deadEntries.length; i += CHUNK) {
    const slice = deadEntries.slice(i, i + CHUNK);
    const values = slice.map(([id, status]) => `('${id}'::uuid, ${quote(status)})`).join(",");
    psql(`
      update staging.product_pages p
         set source_status = v.status,
             category_checked_at = now()
        from (values ${values}) as v(id, status)
       where p.id = v.id;`);
  }
  console.log(`Flagged ${dead.size} dead/redirected pages in source_status.`);
}

// Re-backfill images from the now-updated product_pages.
const imgRes = psql(`
  with upd as (
    update public.images i
       set mother_category_id = pp.mother_category_id
      from staging.product_pages pp
     where pp.id = i.product_page_id
       and i.mother_category_id is distinct from pp.mother_category_id
    returning 1
  )
  select count(*) from upd;`);
console.log(`Updated product_pages (proposed): ${entries.length}. Images re-backfilled: ${imgRes}.`);

const remainingNull = psql("select count(*) from staging.product_pages where mother_category_id is null;");
console.log(`Remaining null product_pages: ${remainingNull}`);

function quote(s) { return `'${String(s).replace(/'/g, "''")}'`; }
function countTag(out, tag) { return out.includes(tag); }
