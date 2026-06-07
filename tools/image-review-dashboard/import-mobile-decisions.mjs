import { readFile } from "node:fs/promises";
import path from "node:path";
import { saveDecisions } from "./server.mjs";

async function main() {
  const decisionFile = process.argv[2];
  if (!decisionFile) {
    throw new Error("Usage: npm run image-review:import-mobile -- /path/to/fwm_mobile_review_decisions_YYYYMMDDTHHMMSSZ.json");
  }

  const payload = JSON.parse(await readFile(path.resolve(decisionFile), "utf8"));
  if (payload.format !== "fwm-mobile-image-review-decisions-v1") {
    throw new Error(`Unexpected mobile decisions format: ${payload.format || "missing"}`);
  }
  if (!Array.isArray(payload.decisions) || payload.decisions.length === 0) {
    throw new Error("The mobile decisions file does not contain any decisions.");
  }

  const result = await saveDecisions({ decisions: payload.decisions });
  console.log(`Imported ${payload.decisions.length} mobile decision(s).`);
  console.log(`Generated ${result.outputs.length} return workbook(s).`);
  console.log(`Returns manifest: ${result.manifestPath}`);
  for (const output of result.outputs) {
    console.log(`- ${output.outputName}: ${output.rowCount} row(s)`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
