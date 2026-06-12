import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

function getArg(name, fallback = "") {
  const prefix = `--${name}=`;
  const inline = process.argv.find((arg) => arg.startsWith(prefix));
  if (inline) return inline.slice(prefix.length);
  const index = process.argv.indexOf(`--${name}`);
  if (index !== -1 && process.argv[index + 1]) return process.argv[index + 1];
  return fallback;
}

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

function timestampForPath(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

async function pathExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function uniqueOutputDirFor(requestedOutputDir, stamp) {
  if (hasFlag("no-unique-output")) return requestedOutputDir;
  const parent = path.dirname(requestedOutputDir);
  const base = path.basename(requestedOutputDir);
  for (let index = 1; index < 1000; index += 1) {
    const suffix = index === 1 ? stamp : `${stamp}_${String(index).padStart(2, "0")}`;
    const candidate = path.join(parent, `${base}_${suffix}`);
    if (!(await pathExists(candidate))) return candidate;
  }
  throw new Error(`Could not find a unique output folder for ${requestedOutputDir}`);
}

function jsonForInlineScript(value) {
  return JSON.stringify(value)
    .replace(/<\//g, "<\\/")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function mimeTypeForImagePath(imagePath) {
  const ext = path.extname(imagePath).toLowerCase();
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  return "image/jpeg";
}

async function rowWithEmbeddedImage(row, sourceDir) {
  if (!row.imagePath?.startsWith("./images/")) return row;
  const imageFilePath = path.join(sourceDir, row.imagePath.replace(/^\.\//, ""));
  const bytes = await readFile(imageFilePath);
  return {
    ...row,
    embeddedImageSource: row.imagePath,
    imagePath: `data:${mimeTypeForImagePath(imageFilePath)};base64,${bytes.toString("base64")}`,
  };
}

async function embedRows(rows, sourceDir) {
  const embedded = [];
  for (const row of rows) {
    embedded.push(await rowWithEmbeddedImage(row, sourceDir));
  }
  return embedded;
}

async function main() {
  const sourceDir = path.resolve(getArg("source"));
  const requestedOutputDir = path.resolve(getArg("output"));
  const runStamp = getArg("run-id", timestampForPath());
  const outputDir = await uniqueOutputDirFor(requestedOutputDir, runStamp);
  const batchSize = Number(getArg("batch-size", "500"));
  const prefix = getArg("prefix", "v032");
  const effectivePrefix = hasFlag("no-unique-prefix") ? prefix : `${prefix}_${runStamp}`;
  if (!sourceDir || !requestedOutputDir || !Number.isFinite(batchSize) || batchSize <= 0) {
    throw new Error("Usage: node split-mobile-bundle.mjs --source <bundle-dir> --output <html-dir> --batch-size 500 --prefix v032 [--run-id 20260611T233000Z] [--no-unique-output] [--no-unique-prefix]");
  }

  await mkdir(outputDir, { recursive: true });
  const [htmlTemplate, css, appJs, bundleJs] = await Promise.all([
    readFile(path.join(sourceDir, "index.html"), "utf8"),
    readFile(path.join(sourceDir, "styles.css"), "utf8"),
    readFile(path.join(sourceDir, "app.js"), "utf8"),
    readFile(path.join(sourceDir, "bundle-data.js"), "utf8"),
  ]);
  const bundle = JSON.parse(bundleJs.replace(/^window\.FWM_MOBILE_BUNDLE = /, "").replace(/;\s*$/, ""));
  const files = [];
  for (let start = 0; start < bundle.rows.length; start += batchSize) {
    const batchNumber = Math.floor(start / batchSize) + 1;
    const rows = bundle.rows.slice(start, start + batchSize);
    const splitFileId = `${bundle.bundleId}_${runStamp}_file_${String(batchNumber).padStart(2, "0")}`;
    const fileBundle = {
      ...bundle,
      bundleId: splitFileId,
      storageNamespace: splitFileId,
      rows: await embedRows(rows, sourceDir),
      batchSize: rows.length,
      splitBatch: {
        batchNumber,
        startRow: start + 1,
        endRow: start + rows.length,
        rowCount: rows.length,
        sourceBundleId: bundle.bundleId,
      },
      batches: [
        {
          bucket: "mixed",
          batchNumber,
          label: `${effectivePrefix} file ${String(batchNumber).padStart(2, "0")}`,
          rowCount: rows.length,
        },
      ],
    };
    const html = htmlTemplate
      .replace('<link rel="stylesheet" href="./styles.css" />', `<style>\n${css}\n</style>`)
      .replace('<script src="./bundle-data.js"></script>', `<script>\nwindow.FWM_MOBILE_BUNDLE = ${jsonForInlineScript(fileBundle)};\n</script>`)
      .replace('<script src="./app.js"></script>', `<script>\n${appJs}\n</script>`);
    const filename = `${effectivePrefix}_${String(batchNumber).padStart(2, "0")}_${rows.length}cards.html`;
    await writeFile(path.join(outputDir, filename), html, "utf8");
    files.push(filename);
    console.log(`Wrote ${filename}`);
  }

  const readme = [
    `${effectivePrefix} copy-to-phone unsorted image review pack`,
    "",
    `Cards: ${bundle.rows.length}`,
    `HTML files: ${files.length}`,
    `Source bundle: ${sourceDir}`,
    `Requested output folder: ${requestedOutputDir}`,
    `Run ID: ${runStamp}`,
    `Generated at: ${new Date().toISOString()}`,
    "",
    "Copy this folder to Internal storage / BrisApps on the phone.",
    "Open one HTML file at a time, sort it, then hit Export before moving to the next file.",
    "These HTML files are self-contained.",
    "",
    "Files:",
    ...files,
    "",
  ].join("\n");
  await writeFile(path.join(outputDir, `${effectivePrefix}_README_COPY_THIS_FOLDER.txt`), readme, "utf8");
  console.log(`Rows: ${bundle.rows.length}`);
  console.log(`Files: ${files.length}`);
  console.log(`Output: ${outputDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
