# ContexA Studio — UI Visibility Fix

This release addresses visibility and interaction feedback in the Clean Minimal Edition.

## What changed

- Replaced the old abstract logo treatment with a high-contrast `CA` monogram inside a solid accent tile. The ContexA wordmark remains visible in its normal, idle state.
- Increased logo size and removed the drop-shadow glow so the mark reads at rest on the sidebar, sign-in screen, and workspace entrance.
- Primary buttons now have a solid theme accent fill and dark readable text even without hover or press.
- Secondary, ghost, destructive, and icon buttons have visible default fills/borders instead of relying on hover/active styling.
- Removed large hover glows from controls. Hover uses small position and material changes; click uses a short tactile compression animation.
- Kept clear keyboard focus indicators and reduced-motion support.
- Kept the 16-theme palette system, local/offline Submission Mode, and backend review workflow.

## Start

Windows: run `run-submission.bat` for an offline rules-only demo, or `run-dev.bat` for development configuration. The application will be available at `http://localhost:5173` after startup.

## Validation performed

- Backend tests: 17 passed.
- TypeScript/JSX syntax transpilation: passed for `App.tsx`, `GovernanceScene3D.tsx`, and `main.tsx`.
- CSS parser: no top-level parse errors.
- A complete frontend production build was not run in this environment because frontend dependencies are not installed here.
