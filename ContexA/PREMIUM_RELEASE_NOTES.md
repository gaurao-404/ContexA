# ContexA Studio — Premium Experience Edition

This package contains the complete ContexA Studio source with the latest visual and submission workflow updates.

## What changed

- 16 distinct color palettes, including Obsidian Champagne, Ember Atelier, Glacier Signal, Orchid Nocturne, Cobalt Flux, Jade Noir, Solar Flare, Rose Quartz, Ocean Depth, Acid Punk, Silver Mist, Kyoto Neon, Copper Bloom, Arctic Opal, Volcanic Glass, and Monsoon Iris.
- Animated sign-in-to-workspace handoff with a dimensional governance scene.
- Animated theme transitions and page/tab transitions with per-section accent colors.
- Adjustable motion profile; reduced-motion accessibility behavior remains supported.
- A compacted interface with less redundant labels and copy.
- Submission mode that disables Ollama and cloud AI so the core rules/review/audit/export flow can be demonstrated without a model service.
- Local Ollama support remains available through the normal development launcher when enabled.

## Start on Windows

1. Extract the ZIP.
2. Run `run-submission.bat` for a repeatable demo that does not depend on Ollama.
3. Open `http://localhost:5173`.
4. Sign in with `admin@contexa.local` / `ContexA!2026` for the development demo, then use **Prepare demo workspace**.
5. Open `http://localhost:5173/palette-motion-lab.html` for the interactive visual preview.

The first run may need internet access to install Python and npm dependencies. After installation, Submission Mode does not need an AI API key or Ollama service.

## Local AI

Use `run-dev.bat` when you want the optional local AI path. Configure the model name in `.env` to match `ollama list`. For example, `nemotron-mini:4b`. No cloud API key is required for local Ollama inference.

## Verification

Backend regression tests: 17 passed. React/TypeScript syntax and CSS structure checks passed. The interactive preview was exercised in Chromium with 16 palettes and no browser JavaScript errors. The full frontend production build has not been verified in this environment because npm dependency installation was previously blocked by registry connectivity.

The default demo/test data are illustrative, not evidence that brand claims or prices have been checked against a company's authoritative product or campaign systems. Connect authoritative sources before using such findings for real publication decisions.
