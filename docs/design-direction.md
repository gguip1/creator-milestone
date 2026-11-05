# Design direction: refinement pass (owner reference, 2026-11-06)

The owner wants the UI to stop looking AI-generated. Reference: a dark, documentation-like developer-tool aesthetic. This is a style reference, not a brand to copy: do not reuse another company's name, logo, or glyphs.

## Principles
- **One dark surface.** Near-black canvas (`#101010`) edge to edge. Dark only, no light-mode rhythm. Slightly lighter fill (`#1a1a1a`) for inputs and code-like blocks.
- **Hairlines instead of shadows.** Cards and dividers use 1 px solid `#3d3a39`. No drop shadows on cards. A 2 px accent border marks the one card awaiting a decision.
- **One accent, used sparingly.** A single electric green (`#00d992`) for primary actions, the "live" or awaiting-decision indicator, and Paid via PayPal. Never for body text. Darker green (`#10b981`) for inline links. No second accent; warnings use muted amber only where a state truly needs attention.
- **Calm type.** Inter for everything narrative; a monospace (JetBrains Mono or Geist Mono as free substitutes) for money, invoice numbers, IDs, timestamps, and quotes from the client message. Display headings weight 400 with slight negative tracking; never heavy. Uppercase tracked eyebrows (Inter 600, 14 px, ~2.5 px tracking) above sections.
- **Fewer ornaments.** Remove sparkle icons and decorative glyphs. Status pills (full radius) only for real states; everything else is plain text. Buttons are 6 px radius rectangles, not pills. Cards 8 px radius.
- **Human copy.** Plain, specific sentences. No slogans repeated on every screen.
- **Real artwork.** Show the commission's sketch and finished art as thumbnails where they belong (sketch review, delivery, client page), labeled as AI-generated sample art.

## Scale
Spacing base 4 px (8, 12, 16, 20, 24, 32, 40, 48, 64). Body 16/26, secondary 14/20, caption 12/16. Display 60/60 on the landing only; page titles 36/40; card titles 20–24.

## Constraints
Keep every functional element, label meaning, and status rule from `docs/design-spec.md` and PRD §11.3. Status must never rely on color alone. Contrast must stay readable at video resolution.
