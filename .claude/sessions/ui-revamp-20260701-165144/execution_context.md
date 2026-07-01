# Execution Context

## Project Patterns
- Flask app factory (`create_app`); pure data layers (storage.py, config.py, markdown.py) — DO NOT touch for this UI revamp.
- Single stylesheet `fishy/static/css/style.css` (~935 lines) organized by feature, with `:root` palette + token variables and a final "cohesive theme" polish section.
- Jinja templates all extend `base.html`. Charts: `chart.js` (per-parameter) + `aggregate.js` (overlay) read an inline `<script type="application/json">` contract from `.reef-chart` / `.reef-aggregate-chart` seams.
- Tests (`pytest`, 254 total) assert on stable CSS class names, `data-*` attributes, DOM structure, and the inline-JSON chart contract — these are INVIOLABLE seams.
- `tests/test_theme.py` reads style.css as TEXT and asserts only PRESENCE of specific names (`--reef-deep/teal/coral/sand/ink/muted/sun`, `--reef-font-body/display`, `--reef-focus`) plus selector/motif strings (`.reef-header::after`, `.reef-footer::before`, `radial-gradient`, `prefers-reduced-motion`). Never rename/remove those; adding is safe.

## Design Tokens (available for all later tasks — from task #1)
- Glass: `--glass-blur-sm/md/lg`, `--glass-fill-weak/--glass-fill/--glass-fill-strong`, `--glass-tint-teal/--glass-tint-deep`, `--glass-border-color/--glass-border-opacity/--glass-border`
- Elevation: `--reef-elev-rest` (=--reef-shadow), `--reef-elev-hover`, `--reef-elev-lifted` (=--reef-shadow-lift)
- Motif: `--motif-wave-height/--motif-wave-scale`, `--motif-coral-size/--motif-coral-inset`, `--motif-accent-opacity`
- Spacing: `--reef-space-3xs` … `--reef-space-2xl`
- Type scale (from task #2): `--reef-text-xs..3xl`, `--reef-leading-tight/snug/normal`, `--reef-tracking-tight/wide` — reuse instead of hard-coding font sizes.
- In-range teal `#01baef` / out-of-range coral `#e4572e`. Palette/gradient/font/radius names all preserved.
- NOTE: footer emoji strip (🐚 🪸 🐠 🌊) lives in CSS `.reef-footer::before` content (cohesive-theme block), NOT in a template — task #6 must handle it there.

## Key Decisions
- UI revamp only: NO functional/behavioral/route/data changes. Zero new runtime dependencies (hand-rolled CSS + inline SVG only). Palette variable names preserved.
- Accessibility de-prioritized per owner, EXCEPT keep the color+shape non-color cue for in/out-of-range (data-viz clarity).

## Known Issues
- Task-executor agents in this environment do NOT have TaskUpdate — the orchestrator marks task status from result files. Agents must still write context-task-{id}.md and result-task-{id}.md.
- CONCURRENT style.css edits: an Edit may fail "file modified since read" — just re-read the relevant region and re-apply. Prefer appending a NEW clearly-commented section at EOF over rewriting earlier rules. NEVER full-file Write a shared file (templates/style.css) — use targeted Edits only.
- Glass system (task #4) already styles `.reef-chart` + `.reef-aggregate-chart` frames. Task #12 should NOT re-add chart-frame CSS — do Plotly JS-side styling only.
- tests/test_theme.py ALSO reads the JS files: asserts exact literals `IN_RANGE_SYMBOL = "circle"` and `OUT_RANGE_SYMBOL = "triangle-up"` in BOTH chart.js and aggregate.js. Never rename/change those. No test asserts JS colors/fonts/layout.

## File Map
- `fishy/static/css/style.css` — all styling + :root tokens (primary surface). New design-token layer added after the "Shared shape language" block.
- `fishy/templates/base.html` — global chrome, fonts, blocks
- `fishy/templates/index.html` — tank shelf landing
- `fishy/templates/parameter.html` (+ `_add_reading_form.html`, `_param_tabs.html`, `_param_reference.html`) — parameter page
- `fishy/templates/aggregate.html` — aggregate view
- `fishy/templates/_notice.html` — malformed-CSV notice
- `fishy/static/js/chart.js`, `fishy/static/js/aggregate.js` — Plotly rendering (styling only)
- Spec: `specs/ui-revamp-SPEC.md`
- `fishy/templates/_icons.html` (NEW, task #3) — reusable icon macro. Use: `{% from "_icons.html" import icon %}` then `icon(name, cls="", title=none, decorative=true)`. Glyphs: `coral, fish, wave` (motifs) + `check, warning, chart, book, shell, tank` (UI). All 24x24 thin-stroke, `stroke=currentColor` (auto-themes), `data-icon="{name}"` hook. `.reef-icon` + `.reef-icon--sm/--lg/--xl` size classes in style.css.

## Wave 3 — Screen Revamps (tasks #7–#11, all PASS, all CSS-only except #8)
Each appended a NEW clearly-commented EOF section to style.css (now ~1905 lines, braces 330/330, 254 tests pass). No template edits except #8. New/notable hooks for later tasks:
- #7 chrome: `.reef-logo` = frosted circular badge; unified active pills (`.reef-switcher__link.is-active` + `.reef-tabs__link.is-active` → `--reef-grad` + lifted shadow); active tab `::after` warm underline; uppercase micro-labels. NOTE: chrome rules live in 4 regions — an EOF append overrides all at equal specificity, but you MUST re-add mobile overrides for any selector you change (later non-media rule beats earlier @media).
- #8 shelf: NEW markup in index.html — `.reef-shelf__hero`, `.reef-shelf__eyebrow` (+`__eyebrow-mark`), `.reef-tank-card__cue` (+`__chevron`) hover affordance. Preserved #5 motif. Token gotcha: it's `--reef-text-base`, NOT `--reef-text-md`.
- #9 parameter, #10 aggregate, #11 empty/notice: pure-CSS tokenization passes (spacing/type/radius). Did NOT re-declare glass bg/backdrop-filter (would clobber #4) — only refined radius/padding/type/hover. #10 bumped `.reef-aggregate-chart`/`.reef-history__scroll` radius to `--reef-radius` to match `.reef-chart`. #11 styled empties purely via shared `.reef-empty`/`.reef-notice` classes + added a notice `@supports` fallback.
- CONCURRENCY LESSON: EOF appends by 5 agents caused repeated "file modified since read" — agents recovered by re-reading the tail/re-anchoring; #8 used `flock $CSS ... >> $CSS` with a `grep -q` idempotency marker. Solo tasks (#13/#14) won't hit this.

## Wave 5 — Micro-interactions (task #13, PASS)
- Added `:root` timing tokens `--reef-dur-fast: .15s`, `--reef-dur-base: .22s`, `--reef-dur-entrance: .42s` (after `--reef-ease`). Appended EOF "TASTEFUL MICRO-INTERACTIONS" section (style.css now ~2005 lines).
- Unified existing transitions onto shared tokens; added `:focus-visible` parity for pills + reference label; ONE non-looping entrance `@keyframes reef-rise-in` (opacity+translateY, iteration 1) on cards/hero/charts; extended reduced-motion block. No `infinite`, no layout shift.
- test_theme.py only asserts the string `prefers-reduced-motion` exists (safe to add more). 254 pass, braces 349/349.

## Wave 6 — Consistency sweep (task #14, PASS)
- 5 targeted style.css reconciling Edits (no template/JS changes): `.reef-card` → tokens; `.reef-add-reading__error` off-palette coral → `--reef-coral-ink`/palette; `.reef-chart` margin/padding/shadow → tokens so `.reef-chart` & `.reef-aggregate-chart` frames use IDENTICAL tokens; `.reef-aggregate__empty` → tokens. App was already highly consistent after prior passes.
- Note: some `rgba(255,107,107,…)` rules (L569 badge--out, L681 aggregate-card--out, L750 history-row--out, L792 notice) are DEAD — overridden by later `255,107,94` palette sections. Left as-is (harmless). No inline style= anywhere; all styling via classes. Responsive @media(max-width:640px) coverage confirmed across chrome/shelf/motif/base. 254 pass, braces 349/349.

## Task History
### Task [1]: Establish design-token layer in :root - PASS
- Extended `:root` in style.css with additive glass/elevation/motif/spacing tokens (see Design Tokens above). Elevation tiers alias existing shadow values for zero visual change. Purely additive — app renders identically at this step.
- Verified: `python -m pytest` 254 passed; brace-balance check.

### Task [3]: Build the marine SVG line-art system - PASS
- NEW `fishy/templates/_icons.html`: `icon(name, cls, title, decorative)` macro (see File Map). Added "Marine SVG line-art system" CSS section in style.css (`.reef-icon` + size mods).
- Cohesive style: viewBox 0 0 24 24, fill=none, stroke=currentColor, stroke-width 1.6, round caps. Decorative by default (aria-hidden + focusable=false); pass decorative=false + title for semantic role=img.
- GOTCHA: don't nest `{# #}` comments in Jinja — inner `#}` closes outer early. Unknown glyph = empty valid <svg>.
- WARNING: style.css edited concurrently by siblings; use unique Edit context. Emoji NOT yet removed from templates (that's #6). #5/#6 consume this macro.
- Verified: all 9 glyphs render under Flask autoescape (no double-escape); `python -m pytest` 254 passed.

### Task [2]: Restyle the light base background and typography - PASS
- style.css: added type-scale tokens (see Design Tokens); evolved `body` background to a layered light backdrop (bubbles + lagoon/sun light + depth gradient white→sand→#fff2df); base h1/h2/h3 hierarchy from type scale; header/footer chrome now use spacing/elevation/type tokens. base.html NOT modified.
- Section titles are h2 with no explicit size → global h2 rule sets hierarchy; component h3s (1.1rem via class) keep theirs. Header/footer styled in BOTH base block and cohesive-theme block — only base block edited.
- Verified: 254/254 pytest; brace balance ok; all test_theme.py strings present.

### Task [4]: Implement the glass UI treatment with fallback - PASS
- style.css: appended a "GLASS UI SYSTEM" section at EOF (~130 lines). Placed last so it wins the cascade at equal specificity without rewriting earlier rules.
- Applied glass to: content/hero/empty cards, `.reef-chart`/`.reef-aggregate-chart`/`.reef-history__scroll` (fill-strong 0.80 backing + teal tint + blur-md), nav pills (fill + blur-sm), save button (translucent deep gradient ≥0.86 so white label legible), `.reef-header` (additive blur-lg + hairline border). `.reef-stat` keeps its teal top-accent (no border shorthand).
- Fallback: `@supports not ((-webkit-backdrop-filter...) or (backdrop-filter...))` swaps every glass surface to opaque tinted solid. Prefixed + standard props emitted.
- Verified: 254/254 pytest; brace balance ok; additive only, zero renames.

### Task [6]: Remove emoji and replace with SVG or typography - PASS
- Replaced ALL emoji with `icon()` glyphs across base.html, index.html, tank.html, aggregate.html, parameter.html + partials (_param_tabs, _add_reading_form, _notice, _param_reference). Each template imports `{% from "_icons.html" import icon %}`. Footer emoji strip → CSS tide-line (kept `.reef-footer::before` selector).
- Mappings: header fish→icon("fish"), shelf coral→icon("coral"), tank-card→icon("tank"), empty→icon("shell"), badges ✓/⚠→icon("check")/icon("warning"), aggregate chart→icon("chart"), reference→icon("book").
- NO test asserts emoji (only visible text like "In range"/"Out of range"/"Aggregate" — all KEPT). 254/254 pass, zero test edits.
- Kept deliberate typographic marks (NOT emoji): breadcrumb ›, back ←, trend arrows ↑↓→, bullet •.
- Used targeted Edits only (no full Write) so #5 can layer motifs cleanly. Footer got ONE targeted style.css Edit.

### Task [5]: Apply coral and wave signature-accent motifs - PASS (attempt 2; attempt 1 crashed mid-run)
- 3 signature accents total: (1) coral icon in index.html shelf title, (2) NEW oversized faint coral silhouette behind landing hero (`.reef-shelf__motif` in index.html), (3) NEW wave divider in tank.html (`.reef-wave-divider`). Appended "MARINE MOTIF ACCENTS" CSS section at EOF.
- Motif sizing via icon em-scaling: set font-size on container (`--motif-coral-size`, etc.). Restraint via opacity (`calc(--motif-accent-opacity * 0.1)` for hero silhouette). aria-hidden + pointer-events:none + behind content (z-index). Responsive shrink at 640px.
- Complements existing CSS chrome motifs (`.reef-header::after` wave-crest, `.reef-footer::before` tide-line). 254/254 pass.

### Task [12]: Fully restyle the Plotly charts - PASS
- chart.js + aggregate.js Plotly styling only (data contract untouched — it's parsed from HTML, not JS). Coral range band (rgba(255,107,94,.10) fill + .28 edge), teal line #01baef w2.5, Nunito/Baloo fonts, muted ticks, subtle gridlines, transparent paper/plot bg (glass frame shows through). Deep-ocean hoverlabel.
- Out-of-range cue preserved: triangle-up + coral #e4572e + larger size. Kept exact `IN_RANGE_SYMBOL="circle"` / `OUT_RANGE_SYMBOL="triangle-up"` (test-asserted).
- Empty-state (.reef-chart__empty) already on-theme via .reef-muted; did not touch style.css.
- Verified: 254/254 pytest; `node --check` both files OK.
