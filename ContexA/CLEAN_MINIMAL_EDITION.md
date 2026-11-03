# ContexA Studio — Clean Minimal Edition

This update simplifies the product UI and fixes the theme picker so each palette changes the actual workspace surfaces, not only the selected swatches.

## UI changes

- Replaced the old three-bar icon with a solid ContexA C/A SVG mark.
- Shortened the main navigation to Home, Content, Review, Rules, Insights, Audit, Team and Settings.
- Removed duplicate workspace labels, group captions, redundant environment text and the persistent footer line.
- Reduced heading metadata and removed the verbose theme descriptions/mood labels from the palette grid.
- Added subtle page-entry motion, selected-navigation icon movement, palette-selection feedback, and a two-tone refraction sweep on palette changes.
- Kept motion respectful of `prefers-reduced-motion`.

## Theme fix

All 16 palettes now define their own base background, sidebar, panel, text, accent and secondary colors. Previously, 11 palettes did not define a complete token set, so the button swatches changed while most of the workspace retained the default palette. The selected theme is still persisted in browser storage.

## Run

On Windows, extract the project and double-click `run-submission.bat`. This is the deterministic, no-Ollama submission configuration. After first-time dependency installation and startup, visit `http://localhost:5173`.

Demo credentials:
- Email: `admin@contexa.local`
- Password: `ContexA!2026`

Choose **Prepare demo workspace** for illustrative sample documents and deterministic findings. Sample metrics/findings should be described as demo data in presentations.

## Validation

- Backend tests: 17 passed.
- TypeScript/TSX syntax transpilation: passed for all source files.
- Stylesheet parser: no CSS parse errors.
- Palette token verification: all 16 themes have distinct background/accent token declarations.
- A full Vite production build was not run in this packaging environment because npm dependency installation timed out. The frontend build should be verified on the target machine after dependencies are available.
