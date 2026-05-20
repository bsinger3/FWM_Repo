## Scripts

This folder is for local automation and data-ingestion scripts that support the Friends With Measurements project.

Recommended split:

- Repo code and automation live in `FWM_Repo`
- Generated datasets and exports live in the sibling `FWM_Data` folder

Current local parent layouts:

- Mac: `/Users/briannasinger/Projects/FWM/`
- Windows: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\`

The starter script in this folder writes to:

- `../FWM_Data/raw/apify/`

Run scripts from anywhere; they resolve paths relative to the repo automatically.

### Amazon Reviews Batch Script

`scrape_amazon_reviews_batches.py`

What it does:

- reads a CSV with an `asin` column
- chunks ASINs into sequential Apify runs
- requests `media_reviews_only`
- saves raw dataset output to `../FWM_Data/raw/apify/batch_###.json`

Expected environment variables:

- `APIFY_TOKEN`
- `APIFY_ACTOR_ID`

You can put them in a repo-local `.env` file instead of setting them in PowerShell every time.

Example `.env` at the repo root:

```dotenv
APIFY_TOKEN=your-token
APIFY_ACTOR_ID=your-actor-id
```

Example:

```powershell
python .\scripts\scrape_amazon_reviews_batches.py .\path\to\asins.csv --batch-size 50
```

Notes:

- Batch size must stay at 100 or below.
- Output is saved as raw JSON exactly as returned by the Apify dataset.
- Existing batch files are preserved; new runs continue numbering from the latest batch file found.

### Direct Amazon Reviews Smoke Scraper

`scrape_amazon_reviews_direct.mjs`

What it does:

- reads a CSV with an `asin` column, or one or more `--asin` values
- visits public Amazon `media_reviews_only` review pages with Playwright
- extracts review text, rating, date, size/color, helpful count, and customer image URLs when review cards are visible
- saves raw JSON output to `../FWM_Data/raw/direct_amazon/batch_###.json`
- stops clearly on CAPTCHA, bot checks, or Amazon sign-in/claim pages instead of attempting to bypass them

Example:

```bash
node scripts/scrape_amazon_reviews_direct.mjs path/to/fresh_asins.csv --batch-size 10 --max-pages 2
```

Single-ASIN smoke test:

```bash
node scripts/scrape_amazon_reviews_direct.mjs --asin B0F8QS88QD --max-pages 1 --debug-dir ../FWM_Data/raw/direct_amazon_debug
```

Notes:

- This is a fallback path for public review pages, not a replacement for Apify when Amazon blocks direct browser access.
- Keep `--sleep-ms` conservative; the default is intentionally slow.
