import { mkdir, copyFile, readFile, readdir, rename, unlink, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readWorkbookRows } from "./server.mjs";

const IMAGE_PROXY = "https://fwm-proxy.bsinger3.workers.dev/?url=";
const __filename = fileURLToPath(import.meta.url);
const execFileAsync = promisify(execFile);
const toolDir = path.dirname(__filename);
const repoRoot = path.resolve(toolDir, "../..");
const mobileSourceDir = path.join(toolDir, "mobile");
const reviewRoot = path.join(repoRoot, "outputs/02_supabase_needs_human_review_cv_first_pass");
const defaultOutputDir = path.join(
  reviewRoot,
  "mobile_review_bundle",
);
const mobileBundleManifestPath =
  process.env.FWM_MOBILE_REVIEW_BUNDLE_MANIFEST ||
  path.join(reviewRoot, "human_labeled_returns/mobile_review_bundle_manifest.json");

function getArg(name, fallback = "") {
  const prefix = `--${name}=`;
  const inline = process.argv.find((arg) => arg.startsWith(prefix));
  if (inline) return inline.slice(prefix.length);
  const index = process.argv.indexOf(`--${name}`);
  if (index !== -1 && process.argv[index + 1]) return process.argv[index + 1];
  return fallback;
}

async function availablePartNumbers(bucket) {
  const prefixByBucket = {
    approve_candidates: "supabase_image_review_approve_candidates_part_",
    needs_human_review: "supabase_image_review_needs_human_review_part_",
    disapprove_candidates: "supabase_image_review_disapprove_candidates_part_",
  };
  const prefix = prefixByBucket[bucket];
  if (!prefix) throw new Error(`Unknown bucket for parts expansion: ${bucket}`);
  const files = await readdir(path.join(reviewRoot, "partial_170000_rows_cv_gated"));
  return files
    .map((file) => file.match(new RegExp(`^${prefix}(\\d{3})\\.xlsx$`))?.[1])
    .filter(Boolean)
    .sort();
}

async function parseParts(value) {
  const raw = String(value || "needs_human_review:001").trim();
  if (raw === "all" || raw === "review:all" || raw === "review_core:all") {
    const needs = await availablePartNumbers("needs_human_review");
    const approvals = await availablePartNumbers("approve_candidates");
    return [
      ...needs.map((part) => ({ bucket: "needs_human_review", part })),
      ...approvals.map((part) => ({ bucket: "approve_candidates", part })),
    ];
  }
  const parsed = raw
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [bucket, partNumber = "001"] = part.split(":");
      return { bucket, part: partNumber === "all" ? "all" : String(partNumber).padStart(3, "0") };
    });
  const expanded = [];
  for (const item of parsed) {
    if (item.part === "all") {
      const parts = await availablePartNumbers(item.bucket);
      expanded.push(...parts.map((part) => ({ bucket: item.bucket, part })));
    } else {
      expanded.push(item);
    }
  }
  return expanded;
}

function extensionForUrl(url) {
  try {
    const ext = path.extname(new URL(url).pathname).toLowerCase();
    if ([".jpg", ".jpeg", ".png", ".webp", ".gif"].includes(ext)) return ext;
  } catch {
    return ".jpg";
  }
  return ".jpg";
}

function mobileRow(row, imagePath, imageDownloadError = "") {
  return {
    bucket: row.bucket,
    packageId: row.packageId,
    partNumber: row.partNumber,
    partFile: row.partFile,
    rowNumber: row.rowNumber,
    rowKey: row.rowKey,
    imageUrl: row.imageUrl,
    rawImageUrl: row.rawImageUrl,
    imagePath,
    imageDownloadError,
    productUrl: row.productUrl,
    defaultDecision: row.defaultDecision,
    cvDecision: row.cvDecision,
    cvReasonCode: row.cvReasonCode,
    cvReasonSummary: row.cvReasonSummary,
    sorterRecommendation: row.sorterRecommendation,
    sorterReasonCodes: row.sorterReasonCodes,
    size: row.display.size,
    colorOrVariant: row.display.colorOrVariant,
    clothingType: row.display.clothingType,
    heightIn: row.display.heightIn,
    weightLbs: row.display.weightLbs,
    waistIn: row.display.waistIn,
    hipsIn: row.display.hipsIn,
    bustIn: row.display.bustIn,
    braBandIn: row.display.braBandIn,
    cupSize: row.display.cupSize,
    inseamIn: row.display.inseamIn,
    userComment: row.display.userComment,
    productTitle: row.display.productTitle,
    productCategory: row.display.productCategory,
    sourceFamily: row.source.sourceFamily,
    sourceSite: row.source.sourceSite,
    sourceFile: row.source.sourceFile,
    sourceRowNumber: row.source.sourceRowNumber,
  };
}

function mimeTypeForImagePath(imagePath) {
  const ext = path.extname(imagePath).toLowerCase();
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  return "image/jpeg";
}

async function rowWithEmbeddedImage(row, outputDir) {
  if (!row.imagePath?.startsWith("./images/")) return row;
  const imageFilePath = path.join(outputDir, row.imagePath.replace(/^\.\//, ""));
  const bytes = await readFile(imageFilePath);
  return {
    ...row,
    imagePath: `data:${mimeTypeForImagePath(imageFilePath)};base64,${bytes.toString("base64")}`,
  };
}

async function readMobileBundleManifest() {
  if (!existsSync(mobileBundleManifestPath)) {
    return {
      format: "fwm-mobile-review-bundle-manifest-v1",
      bundles: [],
      issuedRows: {},
      issuedImageUrls: {},
      issuedImageContentHashes: {},
    };
  }
  const manifest = JSON.parse(await readFile(mobileBundleManifestPath, "utf8"));
  manifest.bundles ||= [];
  manifest.issuedRows ||= {};
  manifest.issuedImageUrls ||= {};
  manifest.issuedImageContentHashes ||= {};
  return manifest;
}

function rowIssueKey(row) {
  return `${row.bucket}::${row.partFile}::${row.rowKey}`;
}

function normalizeImageUrlForDedupe(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw);
    url.hash = "";
    url.search = "";
    url.pathname = url.pathname.replace(/\._[^/.]+_\.(jpe?g|png|webp)$/i, ".$1");
    return url.toString().toLowerCase();
  } catch {
    return raw.replace(/\?.*$/, "").replace(/\._[^/.]+_\.(jpe?g|png|webp)$/i, ".$1").toLowerCase();
  }
}

function imageIssueKey(row) {
  return normalizeImageUrlForDedupe(row.imageUrl || row.rawImageUrl || "");
}

function reviewSimilarityKey(row) {
  const fields = [
    row.source?.sourceSite,
    row.productUrl,
    row.display?.userComment,
    row.display?.size,
    row.display?.heightIn,
    row.display?.weightLbs,
    row.display?.waistIn,
    row.display?.hipsIn,
    row.display?.bustIn,
    row.display?.braBandIn,
    row.display?.cupSize,
  ].map((value) => String(value || "").trim().toLowerCase());
  if (!fields[2]) return "";
  return fields.join("::");
}

async function imageContentHash(downloaded, outputDir) {
  if (!downloaded.imagePath?.startsWith("./images/")) return "";
  const imageFilePath = path.join(outputDir, downloaded.imagePath.replace(/^\.\//, ""));
  const bytes = await readFile(imageFilePath).catch(() => null);
  if (!bytes) return "";
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function localDownloadedImageExists(downloaded, outputDir) {
  if (!downloaded.imagePath?.startsWith("./images/")) return false;
  return existsSync(path.join(outputDir, downloaded.imagePath.replace(/^\.\//, "")));
}

function partLimitKey(row) {
  return `${row.bucket}::${row.partFile}`;
}

async function removeUnusedDownloadedImages(outputDir, includedRows) {
  const imagesDir = path.join(outputDir, "images");
  const keep = new Set(
    includedRows
      .map((item) => item.downloaded.imagePath)
      .filter((imagePath) => imagePath?.startsWith("./images/"))
      .map((imagePath) => imagePath.replace("./images/", "")),
  );
  const files = await readdir(imagesDir).catch(() => []);
  let removed = 0;
  for (const file of files) {
    if (!keep.has(file)) {
      await unlink(path.join(imagesDir, file)).catch(() => {});
      removed += 1;
    }
  }
  return removed;
}

async function writeMobileBundleManifest(manifest) {
  await mkdir(path.dirname(mobileBundleManifestPath), { recursive: true });
  await writeFile(mobileBundleManifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
}

async function fetchImageBytes(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return Buffer.from(await response.arrayBuffer());
  } finally {
    clearTimeout(timeout);
  }
}

async function optimizeImageForPhone(sourcePath, targetPath, maxPixels, quality) {
  try {
    await execFileAsync("sips", [
      "-Z",
      String(maxPixels),
      "-s",
      "format",
      "jpeg",
      "-s",
      "formatOptions",
      String(quality),
      sourcePath,
      "--out",
      targetPath,
    ]);
    return true;
  } catch (error) {
    console.warn(`Could not optimize image ${sourcePath}: ${error.message || error}`);
    return false;
  }
}

async function downloadImage(url, outputDir, allowRemoteFallback, optimizeImages, imageMaxPixels, imageQuality) {
  if (!url) return { imagePath: "", error: "missing image URL" };
  const hash = crypto.createHash("sha256").update(url).digest("hex").slice(0, 24);
  const sourceExt = extensionForUrl(url);
  const filename = optimizeImages ? `${hash}.jpg` : `${hash}${sourceExt}`;
  const imagePath = path.join(outputDir, "images", filename);
  if (existsSync(imagePath)) return { imagePath: `./images/${filename}`, error: "" };
  const sourcePath = optimizeImages ? path.join(outputDir, "images", `${hash}.source${sourceExt}`) : imagePath;

  const attempts = [url, `${IMAGE_PROXY}${encodeURIComponent(url)}`];
  const errors = [];
  try {
    for (const attempt of attempts) {
      try {
        const bytes = await fetchImageBytes(attempt);
        await writeFile(sourcePath, bytes);
        if (optimizeImages) {
          const optimized = await optimizeImageForPhone(sourcePath, imagePath, imageMaxPixels, imageQuality);
          if (optimized) await unlink(sourcePath).catch(() => {});
          else await rename(sourcePath, imagePath).catch(() => {});
        }
        return { imagePath: `./images/${filename}`, error: "" };
      } catch (error) {
        await unlink(sourcePath).catch(() => {});
        errors.push(error.message || String(error));
      }
    }
    return {
      imagePath: allowRemoteFallback ? url : "",
      error: errors.join(" | "),
    };
  } catch (error) {
    return {
      imagePath: allowRemoteFallback ? url : "",
      error: error.message || String(error),
    };
  }
}

async function mapWithConcurrency(items, limit, mapper) {
  const results = new Array(items.length);
  let index = 0;
  async function worker() {
    while (index < items.length) {
      const current = index;
      index += 1;
      results[current] = await mapper(items[current], current);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

async function main() {
  const outputDir = path.resolve(getArg("output", defaultOutputDir));
  const parts = await parseParts(getArg("parts", process.env.FWM_MOBILE_REVIEW_PARTS || "needs_human_review:001"));
  const limit = Number(getArg("limit", process.env.FWM_MOBILE_REVIEW_LIMIT || "0"));
  const batchSize = Number(getArg("batch-size", process.env.FWM_MOBILE_REVIEW_BATCH_SIZE || "0"));
  const skipImages = process.argv.includes("--skip-images");
  const skipStandalone = process.argv.includes("--skip-standalone");
  const requireImages = process.argv.includes("--require-images");
  const skipMissingImages = process.argv.includes("--skip-missing-images");
  const includeSaved = process.argv.includes("--include-saved");
  const includeIssued = process.argv.includes("--include-issued");
  const allowDuplicates = process.argv.includes("--allow-duplicates");
  const allowRemoteFallback = process.argv.includes("--allow-remote-fallback");
  const optimizeImages = process.argv.includes("--optimize-images");
  const imageMaxPixels = Number(getArg("image-max-pixels", process.env.FWM_MOBILE_REVIEW_IMAGE_MAX_PIXELS || "900"));
  const imageQuality = Number(getArg("image-quality", process.env.FWM_MOBILE_REVIEW_IMAGE_QUALITY || "70"));
  const candidateMultiplier = Math.max(1, Number(getArg("candidate-multiplier", process.env.FWM_MOBILE_REVIEW_CANDIDATE_MULTIPLIER || "2")));
  const concurrency = Number(getArg("concurrency", process.env.FWM_MOBILE_REVIEW_IMAGE_CONCURRENCY || "8"));
  const mobileBundleManifest = await readMobileBundleManifest();

  await mkdir(outputDir, { recursive: true });
  await mkdir(path.join(outputDir, "images"), { recursive: true });
  await copyFile(path.join(mobileSourceDir, "index.html"), path.join(outputDir, "index.html"));
  await copyFile(path.join(mobileSourceDir, "styles.css"), path.join(outputDir, "styles.css"));
  await copyFile(path.join(mobileSourceDir, "app.js"), path.join(outputDir, "app.js"));

  const rows = [];
  const rejectionReasons = new Set();
  const includedParts = [];
  const preSeenImageIssueKeys = new Set();
  const preSeenReviewSimilarityKeys = new Set();
  let skippedPreDuplicateRowCount = 0;
  for (const item of parts) {
    const data = await readWorkbookRows(item.bucket, item.part);
    const savedFilteredRows = includeSaved
      ? data.rows
      : data.rows.filter((row) => row.savedDecisionState !== "saved");
    const reviewRows = includeIssued
      ? savedFilteredRows
      : savedFilteredRows.filter((row) => {
          const issuedImageKey = imageIssueKey(row);
          return !mobileBundleManifest.issuedRows[rowIssueKey(row)] &&
            (!issuedImageKey || !mobileBundleManifest.issuedImageUrls[issuedImageKey]);
        });
    const dedupedReviewRows = allowDuplicates
      ? reviewRows
      : reviewRows.filter((row) => {
          const imageKey = imageIssueKey(row);
          const similarityKey = reviewSimilarityKey(row);
          const isDuplicateImage = imageKey && preSeenImageIssueKeys.has(imageKey);
          const isSimilarReview = similarityKey && preSeenReviewSimilarityKeys.has(similarityKey);
          if (isDuplicateImage || isSimilarReview) {
            skippedPreDuplicateRowCount += 1;
            return false;
          }
          if (imageKey) preSeenImageIssueKeys.add(imageKey);
          if (similarityKey) preSeenReviewSimilarityKeys.add(similarityKey);
          return true;
        });
    includedParts.push({
      bucket: data.bucket,
      label: data.label,
      part: data.part,
      filename: data.filename,
      defaultDecision: data.defaultDecision,
      rowCount: data.rows.length,
      includedRowCount: dedupedReviewRows.length,
      skippedSavedRowCount: data.rows.length - savedFilteredRows.length,
      skippedIssuedRowCount: savedFilteredRows.length - reviewRows.length,
      skippedPreDuplicateRowCount: reviewRows.length - dedupedReviewRows.length,
    });
    for (const reason of data.rejectionReasons) rejectionReasons.add(reason);
    rows.push(...(limit > 0 && !allowDuplicates ? dedupedReviewRows.slice(0, limit * candidateMultiplier) : limit > 0 ? dedupedReviewRows.slice(0, limit) : dedupedReviewRows));
  }

  const downloaded = skipImages
    ? rows.map((row) => ({ imagePath: row.imageUrl, error: "image download skipped" }))
    : await mapWithConcurrency(rows, concurrency, (row) => downloadImage(row.imageUrl, outputDir, allowRemoteFallback, optimizeImages, imageMaxPixels, imageQuality));

  const pairedRows = rows.map((row, index) => ({ row, downloaded: downloaded[index] }));
  const availableRows = skipMissingImages
    ? pairedRows.filter((item) => item.downloaded.imagePath && !/^https?:\/\//i.test(item.downloaded.imagePath) && (skipImages || localDownloadedImageExists(item.downloaded, outputDir)))
    : pairedRows;
  const skippedRows = pairedRows.filter((item) => !availableRows.includes(item));
  const seenContentHashes = new Set();
  const seenReviewSimilarityKeys = new Set();
  const perPartCounts = new Map();
  const includedRows = [];
  let skippedDuplicateImageCount = 0;
  let skippedSimilarReviewCount = 0;
  for (const item of availableRows) {
    const contentHash = allowDuplicates ? "" : await imageContentHash(item.downloaded, outputDir);
    const isPreviouslyIssuedImage = contentHash && !includeIssued && mobileBundleManifest.issuedImageContentHashes[contentHash];
    const isBundleDuplicate = contentHash && seenContentHashes.has(contentHash);
    const similarityKey = allowDuplicates ? "" : reviewSimilarityKey(item.row);
    const isSimilarReview = similarityKey && seenReviewSimilarityKeys.has(similarityKey);
    const countKey = partLimitKey(item.row);
    const currentPartCount = perPartCounts.get(countKey) || 0;
    const partIsFull = limit > 0 && currentPartCount >= limit;
    if (isPreviouslyIssuedImage || isBundleDuplicate || isSimilarReview || partIsFull) {
      if (isPreviouslyIssuedImage || isBundleDuplicate) skippedDuplicateImageCount += 1;
      if (isSimilarReview) skippedSimilarReviewCount += 1;
      continue;
    }
    if (contentHash) {
      item.contentHash = contentHash;
      seenContentHashes.add(contentHash);
    }
    if (similarityKey) seenReviewSimilarityKeys.add(similarityKey);
    perPartCounts.set(countKey, currentPartCount + 1);
    includedRows.push(item);
  }
  const bundleId = `partial_170000_rows_cv_gated_mobile_${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const includedDownloads = includedRows.map((item) => item.downloaded);
  const removedUnusedImageCount = await removeUnusedDownloadedImages(outputDir, includedRows);
  const failedDownloads = includedDownloads.filter((item) => item.error).length;
  const remoteFallbacks = includedDownloads.filter((item) => /^https?:\/\//i.test(item.imagePath)).length;
  const bundle = {
    format: "fwm-mobile-image-review-bundle-v1",
    bundleId,
    generatedAt: new Date().toISOString(),
    parts: includedParts,
    imageStatus: {
      localImageCount: includedDownloads.filter((item) => item.imagePath.startsWith("./images/")).length,
      remoteFallbackCount: remoteFallbacks,
      missingImageCount: includedDownloads.filter((item) => !item.imagePath).length,
      failedDownloadCount: failedDownloads,
      skippedRowCount: skippedRows.length,
      skippedPreDuplicateRowCount,
      skippedDuplicateImageCount,
      skippedSimilarReviewCount,
      removedUnusedImageCount,
      optimizedImages: optimizeImages,
      imageMaxPixels: optimizeImages ? imageMaxPixels : "",
      imageQuality: optimizeImages ? imageQuality : "",
      candidateMultiplier: limit > 0 && !allowDuplicates ? candidateMultiplier : "",
      skippedSavedRowCount: includedParts.reduce((total, part) => total + part.skippedSavedRowCount, 0),
      skippedIssuedRowCount: includedParts.reduce((total, part) => total + part.skippedIssuedRowCount, 0),
      offlineReady: failedDownloads === 0 && remoteFallbacks === 0,
    },
    rejectionReasons: Array.from(rejectionReasons).sort(),
    skippedRows: skippedRows.map((item) => ({
      bucket: item.row.bucket,
      partFile: item.row.partFile,
      rowKey: item.row.rowKey,
      imageUrl: item.row.imageUrl,
      imageDownloadError: item.downloaded.error || "image was not available locally",
    })),
    rows: includedRows.map((item) => mobileRow(item.row, item.downloaded.imagePath, item.downloaded.error)),
  };

  if (batchSize > 0) {
    const counters = new Map();
    for (const row of bundle.rows) {
      const current = counters.get(row.bucket) || 0;
      row.batchNumber = Math.floor(current / batchSize) + 1;
      row.batchLabel = `${row.bucket} batch ${row.batchNumber}`;
      counters.set(row.bucket, current + 1);
    }
    bundle.batchSize = batchSize;
    bundle.batches = Array.from(
      bundle.rows.reduce((map, row) => {
        const key = `${row.bucket}::${row.batchNumber}`;
        if (!map.has(key)) {
          map.set(key, {
            bucket: row.bucket,
            batchNumber: row.batchNumber,
            label: row.batchLabel,
            rowCount: 0,
          });
        }
        map.get(key).rowCount += 1;
        return map;
      }, new Map()).values(),
    );
  }

  await writeFile(
    path.join(outputDir, "bundle-data.js"),
    `window.FWM_MOBILE_BUNDLE = ${JSON.stringify(bundle, null, 2)};\n`,
    "utf8",
  );

  if (!skipStandalone) {
    const [htmlTemplate, css, appJs] = await Promise.all([
      readFile(path.join(mobileSourceDir, "index.html"), "utf8"),
      readFile(path.join(mobileSourceDir, "styles.css"), "utf8"),
      readFile(path.join(mobileSourceDir, "app.js"), "utf8"),
    ]);
    const embeddedBundle = {
      ...bundle,
      rows: await Promise.all(bundle.rows.map((row) => rowWithEmbeddedImage(row, outputDir))),
    };
    const standaloneHtml = htmlTemplate
      .replace('<link rel="stylesheet" href="./styles.css" />', `<style>\n${css}\n</style>`)
      .replace('<script src="./bundle-data.js"></script>', `<script>\nwindow.FWM_MOBILE_BUNDLE = ${JSON.stringify(embeddedBundle, null, 2)};\n</script>`)
      .replace('<script src="./app.js"></script>', `<script>\n${appJs}\n</script>`);
    await writeFile(path.join(outputDir, "standalone.html"), standaloneHtml, "utf8");
  }

  const issuedAt = new Date().toISOString();
  for (const row of bundle.rows) {
    mobileBundleManifest.issuedRows[rowIssueKey(row)] = {
      bundle_id: bundle.bundleId,
      issued_at: issuedAt,
      bucket: row.bucket,
      part_file: row.partFile,
      review_row_key: row.rowKey,
      image_url: row.imageUrl,
    };
    const issuedImageKey = imageIssueKey(row);
    if (issuedImageKey) {
      mobileBundleManifest.issuedImageUrls[issuedImageKey] = {
        bundle_id: bundle.bundleId,
        issued_at: issuedAt,
        image_url: row.imageUrl,
      };
    }
    const source = includedRows.find((item) => rowIssueKey(item.row) === rowIssueKey(row));
    if (source?.contentHash) {
      mobileBundleManifest.issuedImageContentHashes[source.contentHash] = {
        bundle_id: bundle.bundleId,
        issued_at: issuedAt,
        image_url: row.imageUrl,
      };
    }
  }
  mobileBundleManifest.bundles.push({
    bundle_id: bundle.bundleId,
    generated_at: bundle.generatedAt,
    output_dir: outputDir,
    parts: includedParts,
    row_count: bundle.rows.length,
    skipped_saved_row_count: bundle.imageStatus.skippedSavedRowCount,
    skipped_issued_row_count: bundle.imageStatus.skippedIssuedRowCount,
  });
  await writeMobileBundleManifest(mobileBundleManifest);

  console.log(`Built mobile review bundle: ${outputDir}`);
  console.log(`Rows: ${bundle.rows.length}`);
  console.log(`Parts: ${includedParts.map((part) => `${part.bucket}:${part.part}`).join(", ")}`);
  console.log(`Saved rows skipped: ${bundle.imageStatus.skippedSavedRowCount}`);
  console.log(`Previously issued rows skipped: ${bundle.imageStatus.skippedIssuedRowCount}`);
  console.log(`Local images: ${bundle.imageStatus.localImageCount}`);
  console.log(`Remote fallback images: ${bundle.imageStatus.remoteFallbackCount}`);
  console.log(`Missing images: ${bundle.imageStatus.missingImageCount}`);
  console.log(`Skipped rows: ${bundle.imageStatus.skippedRowCount}`);
  console.log(`Pre-download duplicate/similar rows skipped: ${bundle.imageStatus.skippedPreDuplicateRowCount}`);
  console.log(`Duplicate images skipped: ${bundle.imageStatus.skippedDuplicateImageCount}`);
  console.log(`Similar reviews skipped: ${bundle.imageStatus.skippedSimilarReviewCount}`);
  console.log(`Unused downloaded images removed: ${bundle.imageStatus.removedUnusedImageCount}`);
  console.log(`Offline ready: ${bundle.imageStatus.offlineReady ? "yes" : "no"}`);
  console.log(skipStandalone ? "Copy this folder to the phone, then open index.html in Chrome." : "Copy this folder to the phone, then open standalone.html in Chrome.");
  if (requireImages && !bundle.imageStatus.offlineReady) {
    throw new Error("The bundle is not offline-ready. Re-run on Wi-Fi or inspect image download failures before using it on the train.");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
