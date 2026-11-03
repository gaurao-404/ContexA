# Interface styles update

Reduced the interface to eight deliberate styles: Minimal, Retro, Blak, Clay, Bento, Editorial, Terminal and Neo-Brutalism.

Each style now changes structure and component treatment, not merely colour: typography, radii, borders, shadows, sidebar treatment, buttons, inputs, headings and dashboard layout. Bento uses a real three-column dashboard grid; Clay uses tactile inset/outer shadows; Editorial uses serif display hierarchy and rules; Terminal uses monospace and square console surfaces; Blak uses square geometry and mono metadata.

The old colorway picker, palette state and palette-transition machinery were removed. Legacy saved values map to the closest retained style. Backend is unchanged.

Validation: static consistency checks passed. Run `cd frontend && npm ci && npm run build`, then inspect all eight styles on desktop and mobile.
