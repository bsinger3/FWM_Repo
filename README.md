# Friends With Measurements

Friends With Measurements is a project exploring clothing fit, sizing, and measurements.

Live site: https://friendswithmeasurements.com

## Deployment

This is a static site hosted on Cloudflare Pages, connected to the GitHub repo [bsinger3/FWM_Repo](https://github.com/bsinger3/FWM_Repo). Deployments happen automatically when changes are pushed to the `main` branch. There is no build step — Cloudflare Pages serves the raw HTML, JS, and CSS files directly.

## Data

Scraped data and generated pipeline artifacts are stored outside this repo in the sibling `FWM_Data` directory so the GitHub repo stays lightweight. On Mac the current layout is `/Users/briannasinger/Projects/FWM/FWM_Data`; on Windows it is `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data`. See [DATA.md](DATA.md) for the local data layout and [AWS_BACKUP_SETUP.md](AWS_BACKUP_SETUP.md) for the current S3 backup and login workflow.
