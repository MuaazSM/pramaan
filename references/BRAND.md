# Pramaan brand kit

This is the single source of truth for how Pramaan looks and sounds. Every UI surface (web app, PDF report, certificate, demo slides) uses it. Machine-readable tokens live in `references/tokens.css`; the logo is `references/logo.svg`. Pattern references from other products are in `references/UI_REFERENCES.md`.

## 1. Brand idea

**Pramaan** (प्रमाण) means *proof*. The product turns opaque surveillance disks into evidence a court can trust. The interface must feel like a precision instrument: calm, dense, exact, and fast. Think "Linear built a forensic lab", not "hacker movie".

Three words guide every decision: **Verified. Traceable. Calm.**

- **Verified**: integrity state is always visible. Every artefact shows its hash status.
- **Traceable**: every number, frame and finding links back to the bytes it came from.
- **Calm**: dark, quiet surfaces; colour is reserved for meaning, never decoration.

## 2. Logo

- Mark: a rounded hexagonal **seal** containing three horizontal **frame bars** of decreasing length (recovered footage) and a **verification dot**. See `logo.svg`.
- Wordmark: `pramaan` in lowercase, Geist Sans Semibold, letter-spacing −0.02em.
- Lockup: mark left, wordmark right, gap = 0.5 × mark height.
- Minimum size: mark 16 px (favicon), lockup 96 px wide.
- On dark surfaces the mark uses `--brand-500` bars on a `--ink-100` outline; on light surfaces, `--brand-600` and `--ink-900`.
- Never add gradients, glows, drop shadows or 3D effects to the logo.

## 3. Colour

Dark mode is the default (examiners work long sessions in dim labs). Light mode exists for printing and daylight review. All values are defined in `tokens.css`.

### Neutrals: "Graphite"

| Token | Hex | Use |
| --- | --- | --- |
| `--ink-950` | `#07080B` | App background (dark) |
| `--ink-900` | `#0B0D12` | Main canvas |
| `--ink-850` | `#10131A` | Panels, sidebar |
| `--ink-800` | `#151922` | Cards, table rows hover |
| `--ink-700` | `#1E2330` | Raised controls, inputs |
| `--ink-600` | `#2A3142` | Borders strong, dividers |
| `--ink-500` | `#3B4458` | Disabled text, subtle icons |
| `--ink-400` | `#5B6479` | Tertiary text |
| `--ink-300` | `#8A93A6` | Secondary text |
| `--ink-200` | `#B7BECC` | Body text on dark |
| `--ink-100` | `#DDE1E8` | Primary text on dark |
| `--ink-50` | `#F3F5F8` | Light-mode canvas |

### Brand: "Seal Indigo"

| Token | Hex | Use |
| --- | --- | --- |
| `--brand-300` | `#B4B5FF` | Focus rings on dark, links hover |
| `--brand-400` | `#8B8DFF` | Links, selected nav, Tier B |
| `--brand-500` | `#6E6CF5` | Primary buttons, active states |
| `--brand-600` | `#5451D6` | Primary on light, pressed |
| `--brand-900` | `#1C1B4A` | Selected row tint (dark) |

### Evidence semantics (reserved meanings; never use these colours decoratively)

| State | Token | Hex | Meaning |
| --- | --- | --- | --- |
| Verified | `--ok` | `#2BD4B4` | Hash re-computed and matches |
| Pending | `--warn` | `#F5B041` | Processing, unverified, needs review |
| Tampered / error | `--danger` | `#F2555A` | Hash mismatch, failed job, integrity risk |
| Recovered (deleted) | `--recovered` | `#E26BF0` | Footage recovered from outside the index |
| Inferred | `--inferred` | `#8B8DFF` | Structure found by format inference (Tier B) |
| AI draft | `--ai` | `#B18CFF` | Claude-drafted text awaiting examiner sign-off |

Every coloured state is also carried by an icon and a text label, never by colour alone.

### Channel palette (multi-camera timeline, 8 categorical)

`#6E9BFF`, `#2BD4B4`, `#F5B041`, `#E26BF0`, `#7DD87D`, `#FF8A65`, `#4FC3F7`, `#C9A7FF` → tokens `--ch-1` … `--ch-8`. Channel colour appears as a 3 px left rule or a timeline track fill, never as full-card backgrounds.

## 4. Typography

- **Geist Sans** for UI, **Geist Mono** for anything machine-exact: hashes, offsets, hex, IDs, timecodes, file paths. Both OFL; install from the `geist` npm package (self-host; the app must work offline).
- Base UI size **13 px** (dense professional tool), line-height 1.5. Body copy in long-form panels 14 px.
- Scale: 11 / 12 / 13 / 14 / 16 / 20 / 24 / 32 / 40 px. Weights: 400, 500, 600 only.
- Numbers: always `font-variant-numeric: tabular-nums` in tables, timecodes and counters.
- Hashes: show the first 8 and last 4 characters (`a41f09c2…9e1d`) with the full value on hover and one-click copy.
- Timecodes: `2026-03-12 14:02:37.480 IST` in mono, with an offset badge when normalised (`+00:05:12 device drift`).

## 5. Layout, shape, depth

- 4 px spacing grid; common steps 4, 8, 12, 16, 24, 32, 48.
- Radius: 6 px controls, 10 px cards, 14 px panels and dialogs, full-round for pills only.
- Borders do the separating: 1 px hairlines (`--line` / `--line-strong`). In dark mode, depth comes from surface steps (ink-900 → 850 → 800), not shadows. Light mode may use one soft shadow token.
- App shell: 240 px collapsible sidebar, 48 px top bar with case context + command palette trigger, content area with resizable split panes.
- Density modes: Comfortable (default) and Compact (tables at 28 px rows).

## 6. Motion

- Durations 120 ms (hover, press), 180 ms (panels, popovers), 240 ms (page transitions, dialogs).
- Easing `cubic-bezier(0.2, 0.8, 0.2, 1)`; exits 20% faster than entrances.
- Motion explains state change (a job finishing, a hash verifying, a frame being located on disk). No idle animations, no bouncing.
- Honour `prefers-reduced-motion` everywhere.
- Signature moment: when a hash verifies, the integrity chip draws a 1-cycle checkmark stroke and settles to teal. That is the only "celebration" in the product.

## 7. Iconography and imagery

- Lucide icons, 16 px, 1.5 px stroke; 20 px in empty states.
- No stock photos, no illustrations of hooded hackers, no padlock clichés.
- Empty states: a small line diagram in the brand style + one sentence + one primary action.
- Thumbnails and video frames are the only photographic content, always shown with a timecode and channel tag.

## 8. Signature components

1. **Integrity chip**: `[● verified] sha256 a41f09c2…9e1d` — state dot + short hash + copy. States: verified, pending, mismatch.
2. **Lineage breadcrumb**: `Disk → Image → Scan run → Recording → Frame`, each segment clickable, ending at the current object.
3. **Custody seal**: footer strip on every case screen showing the audit chain head hash, entry count, and last anchor time.
4. **Tier badge**: `A · parsed`, `B · inferred`, `C · carved` in the tier colours.
5. **Clock stack**: for any frame, four clocks stacked (frame header, index, on-screen OCR, normalised IST) with the chosen value highlighted and confidence shown.
6. **AI draft block**: violet dashed border, "AI draft · needs examiner review" label, every sentence carries evidence-ID chips; an explicit "Accept into report" action.

## 9. Voice and copy

- Precise, calm, legal-grade. Say what happened and to what: "Recovered 214 frames on channel 3 (14:02–14:47 IST) from unindexed space."
- Numbers with units and time zones. Never "a few", "some", "lots".
- Verbs: acquire, verify, parse, recover, infer, normalise, sign, export, anchor.
- Never "AI detected" as a finding. AI output is always "AI draft".
- Errors: what failed, why, what to do next. No apologies, no exclamation marks.
- Indian English spelling (normalise, analyse, licence), IST as the default display zone.

## 10. PDF report and certificate

- A4, Geist Sans body 10.5 pt, Geist Mono for hashes at 8.5 pt.
- Cover: logo lockup, case number, examiner, lab, date; integrity summary box.
- Every page footer: case ID · report hash (short) · page X of Y.
- The BSA Section 63 certificate follows the statutory Schedule structure (Part A, Part B) with hash values in full, mono, one per line.
- Light theme only; semantic colours used sparingly, always with labels.

## 11. Do and don't

| Do | Don't |
| --- | --- |
| Show integrity state on every evidence object | Hide hashes behind a details page |
| Use colour only for evidence semantics and channels | Use gradients, glows, neon, glassmorphism |
| Keyboard-first: every action in the command palette | Bury actions in right-click-only menus |
| Link every finding back to bytes | Show numbers without provenance |
| Keep dark surfaces quiet and layered | Put saturated colour on large areas |
