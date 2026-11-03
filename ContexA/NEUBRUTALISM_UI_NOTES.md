# Neubrutalism UI pass

- New file `frontend/src/neubrutalism.css`, imported after `styles.css` in `src/main.tsx`. Delete that import to revert.
- Flat colour, 3px black borders, hard offset shadows, square corners, Space Grotesk / Space Mono. No blur, glow or gradients.
- All 8 colourways in Settings still work; each now swaps the accent colour.
- `index.html` (fonts, theme-color, title) and `preview.html` (static preview) updated.
- `App.tsx`: only the integrity-ring gradient colours changed.
- Pre-existing, unrelated: `npm run build` (tsc) reports type errors at App.tsx:920 and TrustOSPage.tsx:184. `npx vite build` succeeds.
