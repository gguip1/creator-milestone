# Contrast of the design tokens

Computed with the WCAG 2.x relative-luminance formula. Text needs 4.5:1; controls and focus indicators need 3:1. The hairline `#3d3a39` is decorative (cards and dividers); every control has its own `line-strong` border.

| Pair | Foreground | Background | Ratio | Need | Result |
|---|---|---|---|---|---|
| Body text (ink) | `#f2f0ee` | `#101010` | 16.7:1 | 4.5 | pass |
| Body text (ink) | `#f2f0ee` | `#1a1a1a` | 15.3:1 | 4.5 | pass |
| Secondary text (muted) | `#a9a4a1` | `#101010` | 7.7:1 | 4.5 | pass |
| Secondary text (muted) | `#a9a4a1` | `#1a1a1a` | 7.1:1 | 4.5 | pass |
| Neutral text | `#cfcac7` | `#101010` | 11.7:1 | 4.5 | pass |
| Neutral text | `#cfcac7` | `#1a1a1a` | 10.7:1 | 4.5 | pass |
| Inline link | `#10b981` | `#101010` | 7.5:1 | 4.5 | pass |
| Inline link | `#10b981` | `#1a1a1a` | 6.9:1 | 4.5 | pass |
| Accent text (eyebrow, Paid pill) | `#00d992` | `#101010` | 10.3:1 | 4.5 | pass |
| Accent text on success tint | `#00d992` | `#0d2a21` | 8.3:1 | 4.5 | pass |
| Primary button label | `#101010` | `#00d992` | 10.3:1 | 4.5 | pass |
| Primary button hover | `#101010` | `#00b87a` | 7.4:1 | 4.5 | pass |
| Warn text | `#f2b84b` | `#101010` | 10.6:1 | 4.5 | pass |
| Warn text on warn tint | `#f2b84b` | `#2a2110` | 8.9:1 | 4.5 | pass |
| Warn text on fill | `#f2b84b` | `#1a1a1a` | 9.7:1 | 4.5 | pass |
| Danger text | `#ff8c82` | `#101010` | 8.4:1 | 4.5 | pass |
| Danger text on danger tint | `#ff8c82` | `#2e1816` | 7.4:1 | 4.5 | pass |
| Control border | `#86807d` | `#101010` | 4.9:1 | 3 | pass |
| Control border on fill | `#86807d` | `#1a1a1a` | 4.5:1 | 3 | pass |
| Focus ring / accent border | `#00d992` | `#101010` | 10.3:1 | 3 | pass |
| Hairline (decorative) | `#3d3a39` | `#101010` | 1.7:1 | - | decorative |
