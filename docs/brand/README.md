# LoveOnCue brand

Sheets: `brand-sheet-light.png`, `brand-sheet-dark.png`. Mark: `logo-mark.svg`
(the same file is `web/src/logo.svg`, served as the favicon).

## Idea

A wedding day run well: two linked rings (the couple), resting on time (the cue).
Calm and certain, like a well-run venue at dusk: linen, evergreen, brass candle light.

## Logo

- **Mark:** two linked rings, evergreen and brass, and a brass sparkle for the cue.
  The brass ring passes under the green ring at the top and over it at the bottom.
- **Wordmark:** "Love*on*Cue" in the serif face, "on" in brass italic.
- On evergreen, the green ring turns linen. Keep clear space of half a ring around the mark.
- Smallest size: 16 px for the mark, 120 px wide for the wordmark.

## Colour

| Name | Light | Dark | Use |
|---|---|---|---|
| Evergreen | `#173D35` | `#8CC9AE` | Main actions, logo ring, icon outlines |
| Brass | `#B8893B` | `#D6A54F` | Logo ring, icon details, illustrations. Shapes only, never text |
| Brass ink | `#8A5E12` | `#E0B25E` | "Now" and change text (meets AA) |
| Linen | `#F7F4EE` | `#121815` | Page |
| Card | `#FFFFFF` | `#1B2420` | Cards and sheets |
| Brass wash | `#F5ECD9` | `#3A2F1B` | Icon chips, updates, change pills |
| Blush wash | `#F6E7E2` | `#3A2A27` | Warmth in illustrations. Never a status |
| Ink | `#1E2B27` | `#ECEFEA` | Text |
| Sage / Amber / Clay | `#2F6B4F` / `#7D5200` / `#A33A2B` | lighter tints | Done / Waiting / Urgent only |

Status colours mean status and nothing else. Brand colours never mean status.

## Icons

- Grid 24 × 24, stroke 1.75, round caps and joins. Drawn for this product
  (for example Guests is a round banquet table with chairs; Schedule is the cue line).
- Two tones: the outline in the text colour, a soft fill (`.i-fill`), and one brass
  detail (`.i-accent`, `.i-dot`). Plain contexts show the outline only. The selected
  tab and the Home tiles switch the fill and the brass on.
- Source: `web/src/icons.ts`. Illustrations for empty and welcome screens are there too.
