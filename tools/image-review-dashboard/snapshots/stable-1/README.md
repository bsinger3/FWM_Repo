# Image Review Dashboard stable-1

Local checkpoint of the image review dashboard after the June 8 selection and bulk-action fixes.

Snapshot contents:

- `server.mjs`
- `public/index.html`
- `public/app.js`
- `public/styles.css`
- `image-review-dashboard.spec.ts`

The live dashboard source remains in `tools/image-review-dashboard/`. This folder is only a fallback copy to compare against or restore from if later dashboard experiments go sideways.

To restore this snapshot manually, copy these files back to:

- `tools/image-review-dashboard/server.mjs`
- `tools/image-review-dashboard/public/index.html`
- `tools/image-review-dashboard/public/app.js`
- `tools/image-review-dashboard/public/styles.css`
- `tests/image-review-dashboard.spec.ts`

After restoring, run:

```bash
npm run test:precommit -- tests/image-review-dashboard.spec.ts
npm run image-review
```
