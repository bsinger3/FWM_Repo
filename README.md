# Friends With Measurements

Friends With Measurements is a project exploring clothing fit, sizing, and measurements.

Live site: https://friendswithmeasurements.com

## Deployment

This is a static site hosted on Cloudflare Pages, connected to the GitHub repo [bsinger3/FWM_Repo](https://github.com/bsinger3/FWM_Repo). Deployments happen automatically when changes are pushed to the `main` branch. There is no build step — Cloudflare Pages serves the raw HTML, JS, and CSS files directly.

## Data

Scraped data and generated pipeline artifacts are stored outside this repo in `/Users/briannasinger/Projects/FWM_Data` so the GitHub repo stays lightweight. See [DATA.md](DATA.md) for the local data layout and S3 backup workflow.
