---
name: PepsiCo Agent Studio
description: A connected execution route with a persistent step inspector for customer demonstrations.
colors:
  ink: "#182d43"
  muted: "#5c6c7b"
  faint: "#708091"
  blue: "#2058cb"
  blue-soft: "#edf3ff"
  navy: "#142b45"
  paper: "#fff"
  ground: "#f3f5f7"
  line: "#dce3ea"
  green: "#16745d"
  green-soft: "#eaf6f0"
  amber: "#8c5912"
  amber-soft: "#fff6e5"
  red: "#b63e43"
  red-soft: "#fff0f0"
typography:
  headline:
    fontFamily: "Manrope, sans-serif"
    fontSize: "27px"
    fontWeight: 750
    lineHeight: 1.3
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Manrope, sans-serif"
    fontSize: "15px"
    fontWeight: 750
    lineHeight: 1.6
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Manrope, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
  detail:
    fontFamily: "Manrope, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.9
  label:
    fontFamily: "Manrope, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    lineHeight: 1.6
  mono:
    fontFamily: "ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  status: "5px"
  control: "7px"
  gate: "8px"
  navigation: "9px"
  node: "10px"
  surface: "14px"
spacing:
  compact: "8px"
  small: "10px"
  medium: "16px"
  panel-mobile: "20px"
  panel: "24px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  button-approve:
    backgroundColor: "#1c735c"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  button-reject:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.red}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 11px"
  status-completed:
    backgroundColor: "{colors.green-soft}"
    textColor: "{colors.green}"
    typography: "{typography.label}"
    rounded: "{rounded.status}"
    padding: "4px 9px"
  surface:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.surface}"
  agent-node:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.node}"
    padding: "13px 12px"
  gate:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.gate}"
    padding: "11px 13px"
  navigation-tab:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    padding: "14px 0"
---

# Design System: PepsiCo Agent Studio

## Overview

**Creative North Star: "Execution route and step inspector"**

A crisp working surface makes the order journey the primary visual story. Navy workspace navigation frames white and pale blue-gray panels. A connected route shows the configured agent sequence; selecting a step reveals its handoff in an adjacent inspector, with technical detail available on demand.

The system supports customer demonstrations with drill-down answers. It uses compact labels, restrained color, readable detail text, and explicit execution states. The implemented code is the visual authority; no image-generated comp or separate quality-bar reference was supplied. The direction is recorded in `.run/design-direction.md`, and product constraints in `PRODUCT.md`.

**Key Characteristics:**
- Connected sequential route inside a Temporal workflow surface.
- Persistent step inspector with progressive technical disclosure.
- Cobalt selection, teal completion, amber attention, and red failure or rejection.
- Flat panels, fine borders, and compact self-hosted Manrope typography.
- Responsive stacking with explicit focus and scroll navigation.

## Colors

The palette combines cool neutral working surfaces with restrained execution-state colors. Frontmatter values preserve the CSS custom properties in `app/ui/static/studio.css`.

### Primary
- **Cobalt (`blue`, `blue-soft`)** identifies the primary action, selected tabs, selected nodes, active work, and evidence links. Selection is also expressed through borders or underlines.

### Secondary
- **Completion teal (`green`, `green-soft`)** identifies completed execution and recovered steps.
- **Attention amber (`amber`, `amber-soft`)** identifies retries, pending approval, and demo-output qualification.
- **Failure red (`red`, `red-soft`)** identifies failed execution and rejected orders; these remain distinct text labels.

### Neutral
- **Deep navy (`navy`)** anchors the navigation rail and brand mark.
- **Ink (`ink`)** carries headings and primary text. **Muted slate (`muted`)** carries descriptions and labels; **faint slate (`faint`)** is reserved for subordinate markers.
- **White paper (`paper`)** holds forms and details. **Cool ground (`ground`)** separates the workspace from its panels. **Fine divider (`line`)** defines panel edges and internal groups.

**The State Evidence Rule.** Color accompanies a text state derived from execution data. Selection never implies completion, and an unavailable refresh never becomes a successful result.

## Typography

Manrope is self-hosted from `/static/fonts/manrope-regular.ttf` and `/static/fonts/manrope-bold.ttf`, with `font-display: swap` and a sans-serif fallback. The declarations map the regular file to weights 400–600 and the bold file to 650–800; do not infer that these are variable-font assets. Technical identifiers and raw activity input use the system monospace stack.

The frontmatter records the principal hierarchy. Execution titles use 17px, inspector titles 16px, and panel titles the title token. Main headings reduce to 25px at the mobile breakpoint. Body paragraphs cap at 75ch; result summaries cap at 70ch.

The final CSS cascade sets node titles to 12px on desktop and 11px on mobile; node states, status chips, sync status, and auxiliary labels remain 11px. Detail paragraphs use 12px with generous line height. Raw inspector text ultimately uses 12px because the later preformatted-text rule overrides the earlier raw size; workflow IDs remain 11px monospace. Numeric durations and run counters use tabular figures.

**The Reading Hierarchy Rule.** Use the compact label size for metadata, and the detail role for explanations and outputs. Do not shrink mobile status text below the implemented 11px size.

## Layout

The desktop shell has a 72px white header and a 66px navy navigation rail. The main workspace is capped at 1800px and uses 28px/30px/16px outer padding. The composer is 282px wide, separated from execution by 24px. Within execution, the route takes the flexible column and the inspector takes 267px.

The route uses three equal columns with alternating row direction, preserving configured sequence through arrows and numbered nodes. The final cascade gives node rows a 120px height at every breakpoint. Desktop gaps are 34px vertically and 23px horizontally. The tail is positioned from the actual last node by JavaScript, including custom pipeline lengths.

At widths of at least 1600px, the composer becomes 310px and the inspector 320px; map gaps increase to 38px/36px. At 1250px or below, the composer becomes 260px and the inspector stacks below the route, with a top divider replacing its left divider. Approval actions also stack.

At 800px or below, the rail and avatar disappear and the header becomes 62px. The workspace becomes one column, ordered composer, execution with route and inspector, recent runs, then evidence links. Main padding becomes 23px/16px, map gaps 30px/16px, and node padding 10px/8px. The route retains three columns. Tabs and sync status wrap as needed; status text remains 11px. Evidence links use a single column in the final cascade.

Spacing is deliberately compact, with recurring 8px–16px control gaps and approximately 20px–24px panel padding. This is an observed vocabulary, not a rigid universal spacing grid.

## Elevation & Depth

The interface is flat: background tones, panel borders, and internal dividers establish grouping. It does not use ambient or floating panel shadows. The selected route node uses an inset half-pixel cobalt shadow to reinforce its border. Focus is separate: a 3px outline with a 3px offset (`#5989ef`). A selected gate uses a 2px cobalt outline with a 2px offset.

**The Flat Surface Rule.** Keep containers on the same visual plane; reserve the inset selection stroke for selected route nodes and preserve the separate keyboard focus ring.

## Shapes

Surfaces use the largest rounded token. Nodes are slightly tighter, gates tighter again, and controls compact. Status chips are rounded rectangles rather than pills. State dots and the avatar are circular. Borders are generally 1px; selected tabs use a 2px bottom edge. SVG icons use open strokes, rounded caps and joins, and usually a 20px frame.

## Components

### Buttons

The primary button is cobalt with white text, 12px bold type, and a minimum height of 42px. The full-width run action is at least 44px. Hover deepens the primary background to `#1648b3`; pressing translates it down 1px. Approval uses a separate dark teal action, while rejection is white with red text and a warm border. Busy buttons reduce opacity to 0.55 and use the wait cursor; disabled gate display controls explicitly retain full opacity.

### Inputs and disclosure

White fields use a fine slate border, the control radius, and a minimum height of 42px. Hover strengthens the border; focus changes it to cobalt while retaining the global visible focus ring. Request text is vertically resizable, with a 134px minimum height on desktop and 106px in the mobile composer. Labels are explicitly associated with controls. Native disclosure groups hold approval rules, resilience configuration, technical input, and complete result data.

### Status chips

Compact rounded chips combine a colored dot with an explicit state label. Teal means completion, cobalt active work, amber attention, and red failure or rejection. Neutral chips indicate readiness or unavailable/inactive context. ServiceNow uses “Not reached” after stopped execution or rejected approval, “Not needed” only after a completed result with no incident activity, and “Unavailable” if the completed result is absent.

### Cards and containers

White bordered surfaces group the composer and execution workspace. The route has a very pale tinted ground; the inspector is white with a separating rule. The approval action region uses an amber tint and border, visually attached to execution rather than presented as a modal.

### Navigation

The navy desktop rail contains labeled icon links. Execution tabs use muted text at rest and cobalt text plus an underline when selected. They expose tab/tabpanel relationships, roving tab focus, Left/Right arrow navigation, and Home/End support. Recent runs use full-width buttons, a pale selected background, and `aria-current`.

### Workflow map and inspector

Agent nodes are buttons with an explicit pressed state and accessible labels containing the agent and execution status. Numbered steps alternate direction across rows, while SVG arrows connect actual node geometry. The inspector explains the role, received information, output, retry or failure evidence, and next handoff; technical JSON stays inside disclosure. Demo-model output carries a visible qualification.

Approval and optional ServiceNow appear after the configured agent pipeline. A business rejection is labeled “Order rejected” even when workflow execution completed. The Activity log and Result tabs provide deeper evidence without crowding the map.

When the inspector is stacked (1250px or below), selecting an agent or ServiceNow step focuses and scrolls to it. Selecting a recent run on mobile focuses and scrolls to the execution header. Approval selection has its own scroll path to a pending decision region. These targets are programmatically focusable; focus movement is intentional navigation, not a polling side effect.

### Motion and accessibility

Transitions are short: controls use 180ms, node/nav selection about 200ms, and inspector content a 4px entrance over 200ms in JavaScript (220ms CSS entrance). Active handoff dashes animate over one second; the running node dot breathes over 1.6 seconds. These animations follow real execution states and do not manufacture progress.

Reduced-motion CSS removes animation, transitions, and smooth scrolling; the JavaScript inspector animation becomes zero-duration, and navigation scrolling becomes instant. A skip link, labeled controls, visible keyboard focus, hidden decorative SVGs, form alerts, and a polite live region support navigation and state announcements. This records implemented behavior, not a claim of a complete accessibility audit.

## Do's and Don'ts

### Do:
- **Do** keep the order route readable before exposing technical detail in the inspector.
- **Do** pair state colors with explicit labels and actual execution evidence.
- **Do** preserve self-hosted Manrope and the separate monospace treatment for identifiers and raw data.
- **Do** preserve keyboard focus, reduced-motion behavior, and stacked-layout navigation.
- **Do** distinguish completed execution, rejected orders, unused optional handoffs, and unavailable evidence.

### Don't:
- **Don't** animate simulated progress or imply a selected node has completed.
- **Don't** label an unreached ServiceNow handoff as “Not needed.”
- **Don't** shrink mobile status text below 11px.
- **Don't** replace bordered flat surfaces with floating shadow cards.
- **Don't** present demo-model echoes as verified business recommendations.
