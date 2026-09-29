# UI references

Pramaan's frontend must look and feel like a top-tier product, on par with the best developer and media tools. These are the products to study. **Borrow patterns, never assets**: no logos, illustrations, copy, trademarks or proprietary icon sets from any of these sites. Our visual identity comes only from `references/BRAND.md` and `references/tokens.css`.

If you have web access, open each link and study the named screens before building the matching Pramaan screen. If you don't, rely on the descriptions below.

## Primary references (the quality bar)

| Product | Link | What to take | Where it applies in Pramaan |
| --- | --- | --- | --- |
| Linear | https://linear.app | Information density without clutter; keyboard-first flows; command palette (Cmd/Ctrl+K); crisp sidebar; hairline borders; fast optimistic UI; subtle status icons | App shell, sidebar, case list, command palette, keyboard shortcuts |
| Vercel / Geist | https://vercel.com/geist/introduction | Type scale, monochrome restraint, token discipline, deployment-log style progress, empty states | Typography, job/scan progress logs, empty states |
| Frame.io | https://frame.io | Professional video review: player chrome, frame-accurate scrubbing, filmstrip, comments pinned to timecode, side-by-side compare | Recording player, frame review, annotations on timecode |
| DaVinci Resolve (Edit/Cut page) | https://www.blackmagicdesign.com/products/davinciresolve | Multi-track timeline with synced tracks, playhead, zoomable ruler, track headers | Multi-camera synced timeline |
| Raycast | https://www.raycast.com | Command palette polish, instant search, micro-interactions, dark surfaces | Command palette, search across evidence |
| Sentry | https://sentry.io | Issue detail layout, event breadcrumbs, stack of context panels, timeline of events | Audit log, device-log event view, deletion verdict detail |
| Stripe Dashboard | https://stripe.com | Data tables, detail side panes, status pills, filters as chips, export flows | Recordings table, evidence list, report/export flows |
| Grafana | https://grafana.com | Dense time-series panels, brushing to zoom time ranges | Motion activity strip, per-channel activity heatmap |
| ImHex | https://imhex.werwolv.net | Hex editor layout: offset gutter, byte grid, ASCII pane, pattern highlighting, structure inspector | "Prove it" hex view: frame to disk sectors |
| Palantir Gotham | https://www.palantir.com/platforms/gotham | Investigative workspace tone: serious, dark, entity-centric, timeline + map + graph panes | Overall mood of the case workspace |

## Secondary references (marketing-level polish)

| Product | Link | What to take |
| --- | --- | --- |
| Resend | https://resend.com | Sign-in and first-run screens, restrained hero typography |
| Cal.com | https://cal.com | Settings pages, form layout, toggles |
| Arc / The Browser Company | https://arc.net | Considered motion, small delightful transitions (use sparingly) |

## Anti-references (what the incumbents look like, avoid)

Legacy forensic suites (Windows-forms layouts, ribbon toolbars, modal stacks, grey bevelled buttons, 20 columns of equal weight, tiny unreadable tabs). Pramaan must feel like the opposite: one clear primary action per screen, progressive disclosure, strong hierarchy.

## Pattern checklist per screen

- One primary action per screen, visually obvious.
- Command palette reaches every action and every object (cases, evidence, recordings, frames by timecode).
- Tables: sticky header, tabular numbers, row hover, keyboard row navigation (J/K), column filters as chips, empty/loading/error states designed.
- Long jobs: live progress with stage names, throughput (MB/s), ETA, and a collapsible log, like a deployment log.
- Every evidence object shows its integrity chip and a lineage breadcrumb.
- Split panes are resizable and remember their size.
- Skeleton loaders match final layout; no layout shift.
- Dark mode is the hero; light mode must still pass contrast checks.
