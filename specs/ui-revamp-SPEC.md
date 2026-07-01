# UI Revamp PRD

**Version**: 1.0
**Author**: Anthony Prancl
**Date**: 2026-07-01
**Status**: Draft
**Spec Type**: New feature (existing product)
**Spec Depth**: Detailed specifications
**Description**: The first pass of fishy is functionally okay but its UI is too simplistic. This revamp elevates the existing tropical-reef look into something more dynamic, artistic, and modern — glass-look UI, coral/wave marine motifs, custom SVG line-art in place of most emoji — while keeping the liked color palette and changing no functionality.

---

## 1. Executive Summary

fishy is a local-first Flask web app for reef aquarists to log and visualize water-parameter readings. The app already works; this effort is a **purely visual/experiential revamp**. It keeps the existing reef color palette and all behavior, but pushes the design from "flat white cards on a sand background" toward a layered, artistic, modern look: **frosted-glass UI (including cards), coral and wave marine motifs as signature accents, custom marine SVG line-art replacing most emoji, tasteful micro-interactions, and fully restyled Plotly charts.** The revamp must not break the stable CSS-class names, `data-*` attributes, DOM structure, or inline-JSON chart contract that the app and its tests rely on.

## 2. Problem Statement

### 2.1 The Problem
The current UI is competent but reads as flat and templated. Everything is a plain white `.reef-card` on a flat sandy wash, one accent gradient (`--reef-grad`) is reused throughout, composition is static, visual hierarchy is thin, and emoji (🐠 🪸 🐚 🌊) are used heavily as decoration. The result feels "simplistic" — it does not convey craft, depth, or a distinctive identity.

The person experiencing this is the app's owner/user (a reef aquarist and the developer), who finds the app functional but visually uninspiring and wants it to feel beautiful and modern.

### 2.2 Current State
The app ships a themed-but-shallow foundation:
- A cohesive `:root` palette (deep ocean `--reef-deep`, lagoon teal `--reef-teal`, coral `--reef-coral`, warm sand `--reef-sand`) — **liked, and kept**.
- Google Fonts (Baloo 2 display / Nunito body), soft card shadows, hover lifts, one reused header gradient, radial "bubble" background dots, and a footer emoji strip.
- Single-column, max-960px, card-based layout across: tank shelf (landing) → tank view → parameter page (Plotly chart + stat tiles + add-reading form + readings table + reference accordion) → aggregate view, plus empty states and a malformed-CSV notice.
- Plotly charts with default styling apart from in-range teal / out-of-range coral markers (color + distinct marker shape).

The palette is right; the *design* around it is under-developed. Depth, layering, texture, motif, and glass are absent.

### 2.3 Impact Analysis
This is a personal, local-first tool, so the "cost" is experiential rather than commercial: a plain UI makes a daily-use hobby tool feel less rewarding and less trustworthy at a glance, and undersells the care already in the codebase. There is low functional risk in leaving it, but high upside in fixing it — the underlying structure is solid and the seams are stable, so a visual revamp is high-value and comparatively low-risk.

### 2.4 Business Value
Not a revenue product. Value is craft, daily delight, and pride of ownership: a beautiful, distinctive interface the owner enjoys opening, that showcases the app's data clearly and feels modern rather than generic.

## 3. Goals & Success Metrics

### 3.1 Primary Goals
1. **First-impression wow** — the landing/tank shelf and global chrome look striking and beautiful immediately.
2. **Beautiful data viz** — the charts and stats (the core of the app) look premium and are the star.
3. **Cohesive polish everywhere** — every screen (chrome, shelf, parameter page, aggregate, empty/edge states, notices) feels considered and consistent.
4. **Not templated / modern** — escape the generic look with distinctive, intentional design: glass, coral/wave motifs, custom SVG art.
5. **Zero functional regression** — no behavior, route, data, or seam changes; all existing tests continue to pass.

### 3.2 Success Metrics

Because this is a subjective, single-user visual effort, success is assessed by qualitative acceptance against explicit criteria rather than analytics.

| Metric | Current Baseline | Target | Measurement Method | Timeline |
|--------|------------------|--------|-------------------|----------|
| Owner satisfaction ("wow / modern / not simplistic") | "too simplistic" | Owner confirms all four success goals met | Visual review of each screen against §5 acceptance criteria | End of revamp |
| Screens revamped | 0 of ~all | 100% of in-scope screens (§8.1) | Checklist walkthrough | End of Phase 4 |
| Test suite | Passing | Still passing (no seam/DOM regressions) | `python -m pytest` | Every phase |
| Emoji reduced to deliberate-only | Heavy usage | Emoji removed except a few intentional spots | Grep templates for emoji; manual review | Phase 2 |
| New runtime dependencies added | 0 | 0 | `requirements.txt` unchanged | Every phase |

### 3.3 Non-Goals
- No new features, routes, or changes to reading/logging behavior.
- No backend, storage (`storage.py`), or config (`config.py`) changes.
- No change to chart *data* logic (series building, range resolution, classification) — only chart *styling*.
- Accessibility compliance is **not** a binding goal for this revamp (see §6.4).
- No build tooling, bundler, or CSS/JS framework.

## 4. User Research

### 4.1 Target Users

#### Primary Persona: The Reef Keeper (owner-operator)
- **Role/Description**: A reef aquarium hobbyist who is also the app's developer; runs fishy locally to track water parameters.
- **Goals**: Log readings quickly; see at a glance whether parameters are in range; enjoy a beautiful, calm, ocean-themed tool.
- **Pain Points**: The current UI feels flat and generic; too many emoji; nothing that evokes the beauty of a reef.
- **Context**: Desktop-primary, used at home on localhost; occasional narrower/mobile-width windows.

### 4.2 User Journey Map

```
[Opens localhost] --> [Tank shelf: picks a tank] --> [Parameter tab: reads chart + stats]
        --> [Logs a new reading] --> [Optionally checks Aggregate view] --> [Closes, satisfied]
```

The revamp does not change these steps — it changes how each step *looks and feels*: a striking shelf, glassy chrome, premium charts, and consistent polish throughout.

## 5. Functional Requirements

> "Functional" here means visual/interaction requirements. Every requirement is verified by visual review plus the constraint that all existing seams and tests remain intact.

### 5.0 Cross-Cutting Design Language (applies to all screens)

- **Palette**: Reuse existing `:root` palette variables (`--reef-deep`, `--reef-teal`, `--reef-coral`, `--reef-sand`, etc.). Do not discard them; extend with new tokens (§5.1).
- **Base**: Light, refined — the warm sandy background remains home base, enriched with gradient depth, subtle texture, and layered lighting rather than a single flat wash.
- **Glass**: Frosted/translucent treatment applied **broadly, including cards** (buttons, header/nav, tabs, hero panels, and content cards), using `backdrop-filter` blur + translucent tinted fills + hairline light borders.
- **Motifs**: **Coral** and **wave** marine motifs as **signature accents** — deliberate, memorable placements (e.g., a coral flourish on the landing, wave-form section dividers), not busy or immersive.
- **Icons**: **Custom marine SVG line-art** (coral, fish, wave, and functional UI glyphs) in one cohesive thin-stroke style, replacing the majority of emoji. Emoji permitted only in a few deliberate, sparing spots.
- **Motion**: Tasteful micro-interactions only — refined hovers, smooth transitions, subtle entrance animations; no heavy ambient/looping animation.
- **Charts**: Fully restyled to feel native to the new look (see §5.6).

---

### 5.1 Feature: Design-Token Foundation & Restyled Base

**Priority**: P0 (Critical) — foundation everything else builds on.

#### User Stories
**US-001**: As the owner, I want a structured design-token layer and an enriched base so that the artistic depth is consistent everywhere and future tweaks are one-line changes.

**Acceptance Criteria**:
- [ ] `:root` is extended with a documented **token system**: glass blur/opacity levels, elevation/shadow tiers, motif placement values, and a spacing rhythm scale — layered on top of (not replacing) existing palette vars.
- [ ] The existing palette variable names (`--reef-deep`, `--reef-teal`, `--reef-coral`, `--reef-sand`, `--reef-line`, etc.) are preserved so templates/JS continue to resolve.
- [ ] The page background evolves from a flat sand wash into a layered light backdrop (depth gradient + subtle texture/lighting) that still reads as warm and bright.
- [ ] `base.html` chrome (header, footer) and typography scale are refreshed toward stronger hierarchy without renaming structural classes.
- [ ] The bespoke SVG line-art system is established (inline SVG and/or a reusable Jinja partial) and available to all templates.
- [ ] `python -m pytest` passes.

**Edge Cases**:
- Offline (fonts CDN unreachable): system-font fallback still yields a coherent look (fallback stack already present — keep it).
- Reduced-motion users: honor `prefers-reduced-motion` for the new micro-interactions (retained from current CSS; not a hard gate but kept as-is since it exists).

---

### 5.2 Feature: Glass UI System (with Fallback)

**Priority**: P0 (Critical)

#### User Stories
**US-002**: As the owner, I want frosted-glass surfaces across the UI so that it feels modern and layered — while staying readable.

**Acceptance Criteria**:
- [ ] A reusable "glass" treatment (tokenized blur/opacity/border) is applied broadly: buttons, header/nav, tabs, hero panels, and content cards.
- [ ] Text on glass sits on a sufficiently opaque backing layer so it stays legible over the layered background and motifs (a clarity/robustness rule — not framed as accessibility compliance).
- [ ] A **solid/tinted fallback** renders the same panels acceptably when `backdrop-filter` is unsupported (e.g., `@supports not (backdrop-filter: blur())`) — glass looks intentional, never accidentally unreadable.
- [ ] Existing class names for these surfaces (`.reef-card`, `.reef-add-reading__save`, `.reef-tabs__link`, `.reef-switcher__link`, `.reef-header`, etc.) are reused, not renamed.
- [ ] `python -m pytest` passes.

**Edge Cases**:
- Busy background behind a glass panel: backing layer keeps text readable.
- `backdrop-filter` unsupported: `@supports` fallback engages.

---

### 5.3 Feature: Marine Motifs & Emoji Removal

**Priority**: P1 (High)

#### User Stories
**US-003**: As the owner, I want coral and wave motifs as signature accents and most emoji removed so that the app feels artistic and intentional rather than cluttered.

**Acceptance Criteria**:
- [ ] Coral and/or wave SVG motifs appear as **signature accents** in deliberate spots (e.g., landing hero coral flourish, wave-form dividers between sections/at header/footer edges) — present but not busy.
- [ ] The **majority of emoji are removed** from templates (`base.html` header fish, footer strip `🐚 🪸 🐠 🌊`, shelf/tank-card icons, breadcrumb/section fish, empty-state emoji) and replaced with custom SVG line-art or typographic treatment.
- [ ] Any remaining emoji are few and clearly deliberate (owner-approved spots).
- [ ] Decorative motifs are marked `aria-hidden`/decorative and do not introduce layout breakage on narrow widths.
- [ ] `python -m pytest` passes (note: if any test asserts a specific emoji, update the test to the new marker deliberately and document it).

**Edge Cases**:
- Narrow/mobile widths: motifs scale or hide gracefully, never overlapping content.
- Many tanks/parameters: accent motifs don't repeat into visual noise.

---

### 5.4 Feature: Screen Revamps — Chrome, Shelf, Parameter, Aggregate

**Priority**: P1 (High)

#### User Stories
**US-004**: As the owner, I want every screen restyled cohesively so that there are no plain or rough corners left.

**Acceptance Criteria**:
- [ ] **Global chrome** (`base.html`): header, tank switcher, parameter tabs, footer restyled with glass + motif accents and stronger hierarchy.
- [ ] **Tank shelf / landing** (`index.html`): the first-impression screen is visually striking (hero treatment, glass tank cards, coral accent, refined empty state).
- [ ] **Parameter page** (`parameter.html`, `_add_reading_form.html`, `_param_tabs.html`, `_param_reference.html`): chart, stat tiles, add-reading form, readings table, and reference accordion all restyled cohesively.
- [ ] **Aggregate view** (`aggregate.html`): cards row, overlay chart, and history table restyled to match.
- [ ] **Empty/edge states & notices** (`_notice.html`, `.reef-empty`, `.reef-notice`): restyled on-theme (friendly, glassy, motif-accented) rather than plain.
- [ ] Consistent spacing rhythm, elevation, and motif language across all of the above (verified against §5.1 tokens).
- [ ] `python -m pytest` passes.

**Edge Cases**:
- No tanks / no readings / single reading: empty and degenerate states look intentional and polished.
- Long histories / many parameters: layout stays tidy (existing scroll/wrap behaviors preserved).

---

### 5.5 Feature: Tasteful Micro-Interactions

**Priority**: P2 (Medium)

#### User Stories
**US-005**: As the owner, I want polished micro-interactions so that the UI feels alive without being distracting.

**Acceptance Criteria**:
- [ ] Refined hover/focus states on interactive elements (cards, tabs, switcher, buttons, table rows) using tokenized transitions.
- [ ] Subtle entrance/transition animations on key surfaces (e.g., cards settling in, chart frame) — smooth, brief, non-looping.
- [ ] No heavy ambient/looping background animation.
- [ ] `prefers-reduced-motion` continues to be respected (retained from current CSS).
- [ ] `python -m pytest` passes.

**Edge Cases**:
- Reduced-motion: transforms/animations disabled, layout unaffected.

---

### 5.6 Feature: Fully Restyled Charts

**Priority**: P1 (High)

#### User Stories
**US-006**: As the owner, I want the Plotly charts restyled to match so that the core data viz looks premium and native to the new design.

**Acceptance Criteria**:
- [ ] `chart.js` and `aggregate.js` are restyled: themed fonts, gridlines/axes, background, and a **glass card frame** around each chart, consistent with the design tokens.
- [ ] The target-range band is restyled into a soft, on-brand coral band; the series line uses reef teal.
- [ ] The in-range vs out-of-range distinction is preserved via **more than color** (out-of-range keeps its distinct marker shape + color) — kept as a data-viz clarity feature.
- [ ] Only chart *styling* changes — the inline-JSON data contract, series construction, range resolution, and classification logic are untouched.
- [ ] Charts remain legible at narrow widths and in the aggregate overlay.
- [ ] `python -m pytest` passes.

**Edge Cases**:
- Empty chart seam: existing empty-state (`.reef-chart__empty`) restyled on-theme.
- Overlay with many series (aggregate): themed colors remain distinguishable.

## 6. Non-Functional Requirements

### 6.1 Performance
- No perceptible slowdown from the revamp. `backdrop-filter` and CSS transitions are GPU-friendly; keep blur radii and animated layers modest to avoid jank on lower-end hardware.
- No additional network round-trips beyond assets already loaded (CDN fonts + Plotly). SVG art is inline or served as static files — no new external requests required.

### 6.2 Security
- No change to the security posture: app stays localhost-only (`127.0.0.1` default), no accounts, no new endpoints, no new external calls. Inline SVG must be static, developer-authored markup (no user-supplied SVG injection).

### 6.3 Scalability
- Not applicable in the traditional sense (single-user local app). "Scale" concerns are visual: the design must hold up with many tanks, many parameters, and long reading histories without becoming noisy — handled by the signature-accent (not immersive) motif choice and preserved scroll/wrap behaviors.

### 6.4 Accessibility
- **Explicitly de-prioritized for this revamp, per owner decision.** AA contrast, visible focus rings, and non-color cues are **not binding constraints** and will not gate design choices.
- Existing accessibility affordances in the codebase (focus-visible rings, `prefers-reduced-motion` handling, `aria-*` labels) **may be preserved incidentally** and should not be actively removed, but need not be extended or guaranteed.
- **One intentional exception**, kept purely as a data-viz clarity feature (not framed as accessibility): the in-range/out-of-range status remains distinguishable by **shape/badge/label in addition to color** on charts, badges, and rows.

## 7. Technical Considerations

### 7.1 Architecture Overview
The revamp is confined to the presentation layer: Jinja templates (`fishy/templates/`), the single stylesheet (`fishy/static/css/style.css`), the two chart scripts (`fishy/static/js/chart.js`, `aggregate.js`), and new inline/static SVG art. The Flask app factory, routes, storage, config, and markdown layers are **not** touched. All server-provided data contracts (template context vars, inline-JSON chart payloads, `data-*` attributes) are consumed exactly as today.

### 7.2 Tech Stack
- **Frontend**: Jinja2 server-rendered templates, hand-written CSS (extend existing `style.css` + `:root` tokens), inline/static SVG line-art, Plotly.js (CDN, already used), Google Fonts (CDN, already used).
- **Backend**: Unchanged — Python 3 / Flask app factory (`create_app`).
- **Storage**: Unchanged — CSV via `storage.py`.
- **Infrastructure**: Unchanged — runs on localhost, no build step.

### 7.3 Integration Points
| System | Integration Type | Purpose |
|--------|-----------------|---------|
| Plotly.js (CDN) | Client-side JS | Restyle existing charts (styling only) |
| Google Fonts (CDN) | CSS `<link>` | Typography (already loaded; may refine weights/faces) |
| Flask template context | Jinja variables | Consumed as-is; no context shape changes |

### 7.4 Technical Constraints
- **Zero new runtime dependencies** (spec §7.5 of `fishy-SPEC.md`). No bundler, no CSS/JS framework, no icon library — hand-rolled CSS + inline SVG only.
- **Preserve all seams**: CSS class names, `id`s, `data-*` attributes, DOM structure, and the inline-JSON chart contract that `chart.js`/`aggregate.js` and the test suite depend on (see the "seams" list in `CLAUDE.md`).
- **Append-only, file-is-source-of-truth** storage model is out of scope and untouched.
- **Localhost-only** binding preserved.
- Changes must keep the app working offline (system-font and solid-color fallbacks).

### 7.5 Codebase Context

#### Existing Architecture
- **Presentation**: `base.html` (all pages extend it) → `index.html` (shelf), `tank.html`, `parameter.html`, `aggregate.html`, plus partials `_add_reading_form.html`, `_param_tabs.html`, `_param_reference.html`, `_notice.html`.
- **Styling**: one stylesheet `fishy/static/css/style.css` (~935 lines) organized by feature, with a cohesive `:root` palette + gradient/shadow/typography tokens and a final "cohesive theme" polish section. This is the primary file to evolve.
- **Charts**: `chart.js` (per-parameter) and `aggregate.js` (overlay) read an inline `<script type="application/json">` contract from `.reef-chart` / `.reef-aggregate-chart` seams and call Plotly. In-range teal `#01baef` / out-of-range coral `#e4572e` with a distinct out-of-range marker shape.
- **Data layers** (`storage.py`, `config.py`, `markdown.py`) and the Flask factory (`fishy/__init__.py`) are pure/behavioral and **out of scope**.

#### Integration Points
| File/Module | Purpose | How This Feature Connects |
|------------|---------|---------------------------|
| `fishy/static/css/style.css` | All styling + `:root` tokens | Primary surface to extend (tokens, glass, motifs, screen restyles) |
| `fishy/templates/base.html` | Global chrome, fonts, blocks | Restyle chrome, add SVG art, remove emoji |
| `fishy/templates/index.html` | Tank shelf / landing | Hero + glass cards + coral accent |
| `fishy/templates/parameter.html` (+ partials) | Parameter page | Restyle chart frame, stats, form, table, reference |
| `fishy/templates/aggregate.html` | Aggregate view | Restyle cards, overlay, history table |
| `fishy/templates/_notice.html` + empty states | Notices / edge states | On-theme restyle |
| `fishy/static/js/chart.js`, `aggregate.js` | Plotly rendering | Restyle layout/trace styling only; contract untouched |

#### Patterns to Follow
- **App factory + stable seams**: never touch route/data logic; style against existing classes and `data-*` hooks.
- **Feature-sectioned CSS with `:root` tokens**: extend the existing token-first pattern rather than introducing ad-hoc values.
- **Non-color status cue**: keep the color + shape convention for in/out-of-range (already present in `chart.js`/badges).
- **Graceful degradation**: existing empty-state and malformed-CSV notice patterns are restyled, not removed.

#### Related Features
- **Existing "cohesive theme" section (task #14 in `style.css`)**: the current polish pass is the closest precedent — this revamp deepens it (glass, motifs, tokens) rather than starting over.

## 8. Scope Definition

### 8.1 In Scope
- Design-token foundation in `:root` (glass, elevation, motif, spacing).
- Enriched light base background + refreshed typography/hierarchy.
- Broad glass UI system (incl. cards) with `@supports` fallback + legibility backing.
- Custom marine SVG line-art system; coral/wave signature-accent motifs.
- Removal of the majority of emoji (deliberate few may remain).
- Restyle of **all screens**: global chrome, tank shelf, parameter page (+ partials), aggregate view, empty/edge states, and malformed-CSV notice.
- Tasteful micro-interactions.
- Full restyle of Plotly charts (`chart.js`, `aggregate.js`) — styling only.

### 8.2 Out of Scope
- Any functional/behavioral change, new feature, or new route: reason — this is a visual revamp only.
- Backend, storage (`storage.py`), config (`config.py`), markdown (`markdown.py`), or Flask factory logic changes: reason — seams must stay stable.
- Chart *data* logic (series building, range resolution, classification): reason — only styling changes.
- New runtime dependencies, build tooling, CSS/JS frameworks, or icon libraries: reason — preserve zero-build, local-first ethos.
- Accessibility compliance work: reason — explicitly de-prioritized by owner (§6.4).

### 8.3 Future Considerations
- Optional **dark "aquarium at night" theme** or light/dark toggle (deferred; base stays light for now).
- Optional richer/immersive motif mode if signature accents feel too restrained.
- Optional revisiting of accessibility as a first-class concern in a later pass.

## 9. Implementation Plan

### 9.1 Phase 1: Foundation — Tokens, Base & SVG System
**Completion Criteria**: Token layer and enriched base are in place; SVG art system exists; app renders with no seam/test regressions.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Design tokens | Extend `:root` with glass/elevation/motif/spacing tokens atop existing palette | None |
| Enriched base | Layered light background + refreshed chrome/typography in `base.html` + CSS | Tokens |
| SVG art system | Inline SVG / reusable Jinja partial for marine + UI line-art | None |

**Checkpoint Gate**: Owner reviews the new base look + token approach and confirms direction before broad rollout.

---

### 9.2 Phase 2: Core — Glass System, Motifs & Emoji Removal
**Completion Criteria**: Glass treatment (with fallback) and coral/wave signature accents applied; majority of emoji replaced; tests pass.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Glass UI system | Broad frosted-glass surfaces (incl. cards) + `@supports` fallback + legibility backing | Phase 1 |
| Motif accents | Coral/wave signature-accent placements (hero, dividers, edges) | SVG system |
| Emoji removal | Replace emoji across templates with SVG/typography; update any emoji-asserting tests deliberately | SVG system |

**Checkpoint Gate**: Owner confirms glass legibility and that emoji removal / motif placement feel right (not busy) before per-screen polish.

---

### 9.3 Phase 3: Screen Revamps & Restyled Charts
**Completion Criteria**: Every in-scope screen is cohesively restyled and charts are fully themed; tests pass.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Chrome + shelf | Header/switcher/tabs/footer + striking landing | Phases 1–2 |
| Parameter + aggregate | Chart frame, stats, form, table, reference, aggregate cards/overlay/history | Phases 1–2 |
| Empty states + notices | On-theme restyle of `.reef-empty`, `.reef-notice` | Phases 1–2 |
| Restyled charts | Theme `chart.js` + `aggregate.js` (styling only), keep color+shape cue | Phases 1–2 |

**Checkpoint Gate**: Owner walkthrough of all screens against §5 criteria.

---

### 9.4 Phase 4: Polish — Micro-Interactions & Consistency Pass
**Completion Criteria**: Micro-interactions in place, cross-screen consistency verified, full test suite green, owner signs off on all four success goals.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Micro-interactions | Refined hovers/transitions/entrances; reduced-motion retained | Phase 3 |
| Consistency sweep | Verify spacing/elevation/motif rhythm across every screen | Phase 3 |
| Final verification | `python -m pytest`, run app on localhost, owner review | All |

## 10. Dependencies

### 10.1 Technical Dependencies
| Dependency | Owner | Status | Risk if Delayed |
|------------|-------|--------|-----------------|
| Plotly.js (CDN) | External | In use | None (already loaded) |
| Google Fonts (CDN) | External | In use | Low — system-font fallback covers offline |
| `backdrop-filter` browser support | Browser | Mostly supported | Low — `@supports` fallback specified (§5.2) |

### 10.2 Cross-Team Dependencies
| Team | Dependency | Status |
|------|------------|--------|
| N/A (single developer) | — | — |

## 11. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation Strategy | Owner |
|------|--------|------------|--------------------|-------|
| Broad glass hurts text legibility | Med | Med | Legibility backing layer + solid `@supports` fallback (§5.2) | Dev |
| Motifs make screens feel busy | Med | Med | "Signature accents" (not immersive); checkpoint gate in Phase 2 | Dev |
| Emoji removal breaks emoji-asserting tests | Low | Med | Audit tests up front; update deliberately and document (§5.3) | Dev |
| Restyling charts accidentally touches data logic | High | Low | Change styling only; keep inline-JSON contract + series logic untouched (§5.6) | Dev |
| `backdrop-filter` performance jank | Low | Low | Modest blur radii / limited animated layers (§6.1) | Dev |
| Scope creep into features/behavior | Med | Low | Non-Goals + Out-of-Scope enforced; visual-only mandate | Dev |

## 12. Open Questions

| # | Question | Owner | Due Date | Resolution |
|---|----------|-------|----------|------------|
| 1 | Exact inventory of custom SVG motifs and their per-screen placements | Dev | Phase 1–2 | To be finalized during design |
| 2 | Which few emoji (if any) are intentionally kept | Dev | Phase 2 | Owner to approve during emoji-removal pass |
| 3 | Any tests that assert specific emoji/markers to update | Dev | Phase 2 | Audit during Phase 2 |

## 13. Appendix

### 13.1 Glossary
| Term | Definition |
|------|------------|
| Glass / glassmorphism | Frosted, translucent surfaces using `backdrop-filter` blur + tinted fill + light border |
| Signature accent | A deliberate, memorable motif placement (vs. immersive/all-over decoration) |
| Design token | A named CSS variable capturing a reusable design decision (blur level, elevation, spacing) |
| Seam | A stable interface (CSS class, `data-*`, DOM node, inline-JSON contract) the app/tests depend on |
| Non-color status cue | Distinguishing in/out-of-range by shape/badge/label in addition to color |

### 13.2 References
- `specs/fishy-SPEC.md` — the base product spec (tech-stack decisions, §6/§7 constraints).
- `CLAUDE.md` — modules, seams, template/CSS conventions, and the stable-class contract.
- `fishy/static/css/style.css` — current palette tokens and "cohesive theme" precedent.
- `fishy/static/js/chart.js`, `fishy/static/js/aggregate.js` — chart styling entry points.

---

### Agent Recommendations (accepted during interview)

*The following were suggested based on best practices and accepted by the owner:*

1. **Design-token layer** (Architecture) — formalize glass/elevation/motif/spacing tokens in `:root`. Applies to §5.1 / Phase 1.
2. **Glass fallback** (Robustness) — solid/tinted fallback + legibility backing for frosted panels. Applies to §5.2 / Phase 2.
3. **Non-color status cue** (Data viz) — keep shape/badge in/out-of-range distinction as a clarity feature. Applies to §5.6 / §6.4.

---

*Document generated by SDD Tools*
