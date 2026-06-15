import path from "node:path";

export function fwmDataDir(repoRoot) {
  return process.env.FWM_DATA_DIR || path.resolve(repoRoot, "..", "FWM_Data");
}

export function cvPendingReviewRoot(repoRoot) {
  return path.join(fwmDataDir(repoRoot), "03_cv_annotated_pending_human_review");
}

export function humanReviewedReadyRoot(repoRoot) {
  return path.join(fwmDataDir(repoRoot), "04_human_reviewed_ready_to_publish");
}

export function defaultImageReviewPackageDir(repoRoot) {
  return path.join(cvPendingReviewRoot(repoRoot), "partial_170000_rows_cv_gated");
}

export function defaultImageReviewReturnsDir(repoRoot) {
  return path.join(humanReviewedReadyRoot(repoRoot), "human_labeled_returns");
}
