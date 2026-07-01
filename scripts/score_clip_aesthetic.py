#!/usr/bin/env python3
"""Stage 2 of the CLIP-aesthetic funnel: score each shortlisted image's AUTO-CROPPED
card with the LAION improved-aesthetic predictor (CLIP ViT-L/14 + MLP), so the
"best photos" are judged the way they actually appear after cropping.

Reads the shortlist ndjson from build-clip-shortlist.mjs ({id,url,crop}), downloads
each image, crops to the autocrop rect, runs CLIP + the aesthetic MLP, and writes an
ndjson of {id, aesthetic}. --resume skips ids already scored.

  ../FWM_Data/_venv_clip/bin/python scripts/score_clip_aesthetic.py \
    --input ../FWM_Data/_cache/clip_shortlist.ndjson \
    --output ../FWM_Data/_cache/clip_aesthetic.ndjson \
    --aesthetic-model ../FWM_Data/_models/sac_logos_ava1_l14_linearMSE.pth --resume
"""
import argparse, io, json, os, sys
from concurrent.futures import ThreadPoolExecutor

import requests
import torch
import torch.nn as nn
import open_clip
from PIL import Image

UA = "FWMDevClipAesthetic/0.1 (+https://friendswithmeasurements.com)"


class MLP(nn.Module):
    def __init__(self, dim=768):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(dim, 1024), nn.Dropout(0.2),
            nn.Linear(1024, 128), nn.Dropout(0.2),
            nn.Linear(128, 64), nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.layers(x)


def fetch(url, timeout):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def crop_card(img, crop):
    if not crop:
        return img
    w, h = img.size
    left = max(0, int(crop["leftFrac"] * w))
    top = max(0, int(crop["topFrac"] * h))
    right = min(w, int((crop["leftFrac"] + crop["widthFrac"]) * w))
    bottom = min(h, int((crop["topFrac"] + crop["heightFrac"]) * h))
    if right - left < 8 or bottom - top < 8:
        return img
    return img.crop((left, top, right, bottom))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--aesthetic-model", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"device={device}; loading CLIP ViT-L/14 (downloads ~1.7GB first run)...", file=sys.stderr)
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-L-14", pretrained="openai", force_quick_gelu=True
    )
    model = model.to(device).eval()
    mlp = MLP(768)
    mlp.load_state_dict(torch.load(args.aesthetic_model, map_location="cpu"))
    mlp = mlp.to(device).eval()

    rows = []
    with open(args.input) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if args.limit:
        rows = rows[: args.limit]

    done, mode = set(), "w"
    if args.resume and os.path.exists(args.output):
        with open(args.output) as fh:
            for line in fh:
                try:
                    done.add(json.loads(line).get("id"))
                except Exception:
                    pass
        mode = "a"
    rows = [r for r in rows if r.get("id") not in done]
    total = len(rows)
    print(f"{total} to score ({len(done)} done)", file=sys.stderr)

    def load(row):
        try:
            img = crop_card(fetch(row["url"], args.timeout), row.get("crop"))
            return row, preprocess(img), None
        except Exception as e:  # noqa: BLE001
            return row, None, str(e)[:160]

    written = 0
    out = open(args.output, mode)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool, torch.no_grad():
            batch_rows, batch_tensors = [], []

            def flush():
                nonlocal written
                if not batch_tensors:
                    return
                x = torch.stack(batch_tensors).to(device)
                emb = model.encode_image(x).float()
                emb = emb / emb.norm(dim=-1, keepdim=True)
                scores = mlp(emb).squeeze(-1).cpu().tolist()
                for r, s in zip(batch_rows, scores):
                    out.write(json.dumps({"id": r["id"], "aesthetic": round(float(s), 4)}) + "\n")
                    written += 1
                batch_rows.clear()
                batch_tensors.clear()
                out.flush()
                print(f"{written}/{total}", file=sys.stderr, flush=True)

            for row, tensor, err in pool.map(load, rows):
                if tensor is None:
                    out.write(json.dumps({"id": row["id"], "aesthetic": None, "error": err}) + "\n")
                    written += 1
                    continue
                batch_rows.append(row)
                batch_tensors.append(tensor)
                if len(batch_tensors) >= args.batch:
                    flush()
            flush()
    finally:
        out.close()
    print(f"done: wrote {written}", file=sys.stderr)


if __name__ == "__main__":
    main()
