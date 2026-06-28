# KIS Strategy Alert Design System

## 1. Atmosphere & Identity

A compact operations dashboard for trading strategy checks. It should feel quiet, dense, and readable: tables, badges, and small status cards expose decision data without marketing decoration. The signature is muted financial control, using slate surfaces with restrained blue, green, amber, red, and pink status accents.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
|------|-------|-------|------|-------|
| Surface/page | --surface-page | #f1f5f9 | #0f172a | Admin page background |
| Surface/primary | --surface-primary | #ffffff | #1e293b | Sections and content panels |
| Surface/secondary | --surface-secondary | #f8fafc | #334155 | Tables, cards, placeholder states |
| Surface/muted | --surface-muted | #e2e8f0 | #475569 | Disabled and secondary buttons |
| Text/primary | --text-primary | #1e293b | #f8fafc | Main headings and table text |
| Text/secondary | --text-secondary | #64748b | #cbd5e1 | Labels, captions, secondary copy |
| Text/inverse | --text-inverse | #ffffff | #ffffff | Text on strong accents |
| Border/default | --border-default | #e2e8f0 | #334155 | Panels, table rules |
| Border/subtle | --border-subtle | #cbd5e1 | #475569 | Inputs, dashed empty states |
| Accent/primary | --accent-primary | #3b82f6 | #60a5fa | Primary actions and active tabs |
| Accent/hover | --accent-hover | #2563eb | #93c5fd | Primary hover state |
| Status/success | --status-success | #16a34a | #22c55e | Bullish, pass, active |
| Status/success-bg | --status-success-bg | #dcfce7 | #14532d | Success badges |
| Status/warning | --status-warning | #f59e0b | #fbbf24 | Warning and stale state |
| Status/warning-bg | --status-warning-bg | #fef3c7 | #78350f | Warning badges |
| Status/error | --status-error | #dc2626 | #ef4444 | Bearish, fail, destructive |
| Status/error-bg | --status-error-bg | #fee2e2 | #7f1d1d | Error badges |
| Status/pink | --status-pink | #ec4899 | #f472b6 | MA5 strategy accent |
| Strategy/golden | --strategy-golden | #1e3a5f | #1e3a5f | Golden-cross strategy panel |
| Strategy/golden-end | --strategy-golden-end | #2d5a87 | #2d5a87 | Golden-cross panel gradient |

### Rules

- Use slate surfaces for structure and semantic colors only for status, state, or primary actions.
- Do not introduce decorative gradient or accent colors outside strategy overview panels.
- Extend this table before adding a new repeated color role.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Tracking | Usage |
|-------|------|--------|-------------|----------|-------|
| H1 | 32px | 700 | 1.25 | 0 | Page title |
| H2 | 16px | 600 | 1.4 | 0 | Section title |
| H3 | 16px | 600 | 1.4 | 0 | Compact panel title |
| Body | 14px | 400 | 1.5 | 0 | Default UI text and controls |
| Body/sm | 13px | 400 | 1.5 | 0 | Tables and buttons |
| Caption | 12px | 500 | 1.4 | 0 | Labels, helper text |
| Overline | 11px | 600 | 1.3 | 0.08em | Sidebar section labels |
| Numeric | 12px | 400 | 1.5 | 0 | Tabular market metrics |

### Font Stack

- Primary: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
- Mono: ui-monospace, SFMono-Regular, monospace

### Rules

- Market numbers use the mono stack or `font-variant-numeric: tabular-nums`.
- Body text stays at 13px or larger inside data tables and 14px or larger in form surfaces.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a base of 4px.

| Token | Value | Usage |
|-------|-------|-------|
| --space-1 | 4px | Inline gaps and badge padding |
| --space-2 | 8px | Compact rows, tabs, small controls |
| --space-3 | 12px | Form rows and table horizontal rhythm |
| --space-4 | 16px | Section internals and strategy steps |
| --space-5 | 20px | Section padding |
| --space-6 | 24px | Page padding and large vertical rhythm |
| --space-10 | 40px | Empty-state padding |

### Grid

- Max content width: 1400px
- Sidebar width: 200px desktop; overlay up to 320px mobile
- Breakpoints: mobile at 768px, desktop default above 768px

### Rules

- Tables prioritize scan density over decorative whitespace.
- Layout changes must preserve readable rows without horizontal text overlap.

## 5. Components

### Stock Table

- **Structure**: `.stock-table` with semantic `thead`, `tbody`, `th`, and `td`.
- **Variants**: strategy scan, universe list, history list.
- **Spacing**: 10px vertical and 12px horizontal cell padding.
- **States**: hover row background, selected row background, placeholder row for empty/loading.
- **Accessibility**: headers name every metric column; empty rows use a single colspan cell.
- **Motion**: none.

### Status Badge

- **Structure**: inline `.state-badge` with semantic status classes.
- **Variants**: strategy state, financial state, MA5 state.
- **Spacing**: 4px by 10px padding.
- **States**: static status display.
- **Accessibility**: text label must not rely on color alone.
- **Motion**: none.

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro | 100-150ms | ease-out | Button press and hover |
| Standard | 200ms | ease | Sidebar and tab transitions |

### Rules

- Interactive controls need hover and focus states.
- Prefer instant table updates over animated row movement for scan results.

## 7. Depth & Surface

### Strategy

Mixed, but restrained: section cards use borders, strategy overview panels use tonal gradients, and no generic box shadows.

| Type | Value | Usage |
|------|-------|-------|
| Border/default | 1px solid var(--border-default) | Sections, stat cards, table rules |
| Border/subtle | 1px solid var(--border-subtle) | Inputs and empty-state outlines |
| Radius/sm | 4px | Compact buttons and badges |
| Radius/md | 6px | Inputs, tabs, strategy steps |
| Radius/lg | 8px | Sections, stat cards, last-search |

