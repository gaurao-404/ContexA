# ContexA visibility and motion fix

## What changed
- Removed `!important` from root custom-property fallbacks so `:root[data-theme=...]` can actually switch the color palette.
- Replaced self-referential `--teal: var(--teal)` / `--purple: var(--purple)` declarations with real default fallback colors.
- Made the ContexA CA monogram’s background fill visible and its foreground contrast reliable.
- Made primary/secondary/icon and login demo-profile controls readable at rest; disabled primary actions remain visibly styled while their action is busy.
- Added short logo, navigation-selection and page-section transitions plus tactile button feedback without persistent glow.
- Preserved reduced-motion support and the existing offline submission launcher.

## Start
Run `run-submission.bat` on Windows, then open the URL printed by Vite (normally http://localhost:5173).
