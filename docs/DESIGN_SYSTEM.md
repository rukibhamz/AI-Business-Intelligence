# Cognitive Logic — Design System

> Living reference for UI implementation. Screen mockups are applied against these tokens.
> Source of truth for agents: match this document before inventing styles.

**Brand name:** Cognitive Logic  
**Aesthetic:** Refined Minimalism (Linear / Notion–adjacent)  
**Audience:** B2B — analysts, executives, product managers  
**Tone:** Calm authority; UI recedes so data and AI insights lead

---

## 1. Color Tokens

| Token | Hex | Use |
|-------|-----|-----|
| `background` | `#f8f9fa` | App canvas (also `#F9FAFB` in prose) |
| `on-background` | `#191c1d` | Default text on canvas |
| `surface` | `#f8f9fa` | Base surface |
| `surface-container-lowest` | `#ffffff` | Cards, sidebar (Level 1) |
| `surface-container-low` | `#f3f4f5` | Subtle panels |
| `surface-container` | `#edeeef` | Nested containers |
| `surface-container-high` | `#e7e8e9` | Elevated panels |
| `surface-container-highest` / `surface-variant` | `#e1e3e4` | Table headers, muted fills |
| `on-surface` | `#191c1d` | Primary text |
| `on-surface-variant` | `#454654` | Secondary text |
| `outline` | `#757686` | Strong borders / icons |
| `outline-variant` | `#c5c5d7` | Soft borders |
| `primary` | `#2036bd` | Brand / strong primary |
| `primary-container` | `#3e52d5` | **Cobalt Indigo** — primary actions |
| `on-primary` | `#ffffff` | Text on primary |
| `on-primary-container` | `#d7daff` | Text on primary container |
| `secondary` | `#4648d4` | Secondary actions |
| `secondary-container` | `#6063ee` | Secondary fills |
| `tertiary` | `#7e3100` | Accent (sparingly) |
| `error` | `#ba1a1a` | Errors / destructive |
| `error-container` | `#ffdad6` | Soft error bg |
| `on-error-container` | `#93000a` | Error text on soft bg |
| `inverse-surface` | `#2e3132` | Inverse / dark chips |
| `inverse-on-surface` | `#f0f1f2` | Text on inverse |
| `inverse-primary` | `#bbc3ff` | Primary on dark |

**Semantic (utility only — trends / health / alerts):**

| Role | Soft bg | Text |
|------|---------|------|
| Success | Green-50 | Green-700 |
| Warning | Amber-50 | Amber-700 |
| Danger | `#ffdad6` | `#93000a` |

**Borders (practical):** Slate-200 `#E5E7EB`, row dividers Slate-100 `#F3F4F6`  
**Dark mode canvas:** `#0B0E14` (not pure black)

---

## 2. Typography

**Family:** **Manrope** (400/500/600/700/800) for everything — UI, nav, labels, and
metrics. **JetBrains Mono** for generated SQL, code, and metric badges.
Loaded in `frontend/index.html`; exposed as `--cl-font-body`, `--cl-font-metric`,
`--cl-font-label`, and `--cl-font-mono`.

| Class | Size | Weight | Line | Tracking |
|-------|------|--------|------|----------|
| `text-metric-lg` | 44px (32px &lt;768px) | 800 | 52px | -0.03em |
| `text-metric-md` | 30px | 700 | 38px | -0.025em |
| `text-metric-sm` | 22px | 700 | 30px | -0.02em |
| `text-headline-sm` | 18px | 700 | 26px | -0.02em |
| `text-body-md` | 15px | 400 | 23px | -0.006em |
| `text-body-sm` | 13.5px | 400 | 20px | -0.004em |
| `text-label-caps` | 11px | 700 | 16px | 0.09em, uppercase |
| `text-mono-data` | 12.5px | 400 | 18px | JetBrains Mono |

**Hierarchy rule:** one family, separated by weight and tracking. Numerals use
`font-variant-numeric: tabular-nums` so KPI values and deltas do not jitter as
live data refreshes.

---

## 3. Spacing & Layout

- **Base unit:** 4px — all spacing multiples of 4
- **Scale:** xs 4 · sm 8 · md 16 · lg 24 · xl 40 · (also 12, 32, 64)
- **Container max:** 1440px · **Gutter:** 24px
- **Sidebar:** floating rail **264px** expanded / **76px** collapsed (12px inset gap, 16px radius); below 1024px it becomes an off-canvas drawer with a scrim
- **Grid:** 12-column fixed-fluid hybrid

**Breakpoints**

| Name | Width | Columns | Margin |
|------|-------|---------|--------|
| Mobile | &lt; 640px | 1 | 16px |
| Tablet | 641–1024px | 6 | 24px |
| Desktop | &gt; 1024px | 12 | 24px |

**Tables:** Standard row padding 16px vertical; Compact 8px.

---

## 3b. Theming

Two themes ship: light (default) and dark. The active theme is stamped as
`data-theme="light" | "dark"` on `<html>` by an inline script in `index.html`
(before first paint, so there is no flash) and toggled from the topbar or the
account menu. The choice persists in `localStorage` under `cl_theme`.

**Rule:** every colour token gets its definition on bare `:root` first; the dark
block only *redefines* tokens. No token may exist solely inside a theme block.

**Colour scheme:** the four scheme colours (`--cl-primary`,
`--cl-primary-container`, `--cl-secondary`, `--cl-secondary-container`) are set
on `document.documentElement` at runtime from the saved setting. Accent roles
(`--cl-accent`, `--cl-accent-strong`, `--cl-accent-quiet`, `--cl-accent-hover`,
`--cl-on-accent`) derive from them with `color-mix`, and the dark theme
re-derives them lighter so contrast holds.

> Because a custom property resolves its `var()` references against the element
> it is **declared** on, scheme colours must be set on `:root` — setting them on
> a descendant will not re-resolve the derived accent tokens.

**Use `--cl-accent*` for interactive accents in components, never the raw
`--cl-primary*` values** — the raw values are scheme input, not theme-safe output.

**Charts:** `--cl-chart-1` … `--cl-chart-8`, plus `--cl-chart-grid` and
`--cl-chart-axis`. Recharts receives these as `var(...)` strings for `fill` and
`stroke`, so charts recolour with the theme without a re-render.

---

## 4. Elevation (Tonal Layers)

| Level | Token | Use |
|-------|-------|-----|
| 0 Background | `--cl-background` | Canvas |
| 1 Cards / Sidebar | `--cl-shadow-level-1` | 1px `--cl-border` + hairline shadow |
| 2 Popovers / Panels | `--cl-shadow-level-2` | 1px border + soft shadow |
| 3 Modals / Palette | `--cl-shadow-level-3` | 1px border + lifted shadow |
| Active / hover | `--cl-ring-active` | Accent tint ring |
| Focus | `--cl-focus-ring` | 3px accent ring on `:focus-visible` |

Shadow tokens are redefined in the dark theme (heavier, since tinted borders
carry less separation on a dark canvas).

---

## 5. Shape

| Token | Radius | Use |
|-------|--------|-----|
| `--cl-radius-sm` | 6px | Tags, tooltips, menu items |
| `--cl-radius` | 10px | Buttons, inputs, nav items |
| `--cl-radius-md` | 12px | Panels, popovers |
| `--cl-radius-lg` | 16px | Cards, sidebar, modals, empty states |
| `--cl-radius-xl` | 24px | — |
| `--cl-radius-full` | 9999px | Pills, avatars |

---

## 6. Components (contract)

- **Primary button:** `--cl-accent` fill, `--cl-on-accent` text, `--cl-radius`
- **Secondary button:** White bg, 1px Slate-200, Slate-900 text
- **Ghost button:** `--cl-accent-strong` text only
- **AI input:** Wide field + sparkle icon; focus = 1px indigo border
- **Metric card:** `metric-lg` value → `label-caps` label → semantic chip / sparkline
- **Data table:** `label-caps` headers on gray fill; 1px bottom borders only
- **Chips:** Soft semantic bg + strong semantic text
- **Nav:** grouped (Workspace / Intelligence / Configure); active = `--cl-accent-quiet` fill + 3px accent left marker; collapsed rail shows hover tooltips
- **Empty state / skeleton / inline message / spinner:** `components/Feedback.tsx`
- **Search:** topbar button opens the command palette (Ctrl/Cmd+K) over pages, data sources, and past questions

---

## 7. Implementation map

| Artifact | Path |
|----------|------|
| This doc | `docs/DESIGN_SYSTEM.md` |
| CSS variables | `frontend/src/styles/tokens.css` |
| App base styles | `frontend/src/index.css` |
| Fonts + theme bootstrap | `frontend/index.html` |
| Theme helpers | `frontend/src/lib/theme.ts` |
| Value formatting | `frontend/src/lib/format.ts` |
| Navigation model | `frontend/src/layouts/navigation.ts` |
| Shared feedback UI | `frontend/src/components/Feedback.tsx` |
| Command palette | `frontend/src/components/CommandPalette.tsx` |
| Live charts | `frontend/src/components/LiveChart.tsx` |

**Screen backlog**

| Screen | Status | Mockup | Implementation |
|--------|--------|--------|----------------|
| Login | ✅ Done | `docs/mockups/login.png` + Stitch `login_stitch.html` | `frontend/src/pages/LoginPage.tsx` |
| App shell / sidebar | ✅ Done | `docs/mockups/sidebar-style.png` | `AppShell.tsx` — floating rail, grouped nav, collapse, mobile drawer, theme toggle |
| Data sources | ✅ Done | Stitch mockup | `DataSourcesPage.tsx` |
| AI chat / query | ✅ Done | Stitch mockup | `AskAiPage.tsx` (New Analysis) |
| Q&A History | ✅ Done | `docs/mockups/qa-history.png` + `stitch_qa_history/code.html` | `HistoryPage.tsx` |
| Findings / Reports | ✅ Done | `docs/mockups/findings.png` + `stitch_findings/code.html` | `FindingsPage.tsx` (live findings + pinned reports) |
| Overview dashboard | ✅ Done | Stitch mockup | `OverviewPage.tsx` |
| Settings | ✅ Done | Stitch mockup | `SettingsPage.tsx` |

---

## 8. Agent rules

1. Prefer tokens over raw hex in new UI code — and never define a colour only inside a theme block.
1b. **The UI renders live data only.** Never ship placeholder KPIs, sample findings, or fake chart series. When the data cannot support a metric, render an empty state that says what is missing and links to the fix.
1c. Use `--cl-accent*` for interactive accents, not the raw `--cl-primary*` scheme inputs.
1d. Mark decorative Material Symbols spans `aria-hidden="true"`; icon-only controls need an `aria-label`.
2. Do not introduce purple gradients, heavy multi-shadows, or decorative glow aesthetics that conflict with Refined Minimalism.
3. When a mockup conflicts with tokens, prefer the mockup for that screen and note the exception here.
4. Update §7 screen backlog when a mockup is implemented.
