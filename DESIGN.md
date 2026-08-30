# Volta Design System

This file is the visual contract for Volta. Any interface change must preserve the
product's role: an operational decision console for drayage, with Nauta visible as the
connected intelligence layer around it.

## Product character

Volta should feel calm, precise, and decisive under time pressure. It is not a marketing
site, a generic tracking portal, or a chat interface. Operators should be able to answer
four questions in seconds:

1. Which operation needs attention now?
2. Why is it ready or at risk?
3. What action can I safely take?
4. What evidence supports the current state?

Prefer an information hierarchy that leads from urgency to action to evidence. Do not
add decorative dashboards, speculative metrics, or multi-agent canvases.

## Identity and relationship to Nauta

- **Volta is the product identity.** Use the Volta mark and name in the primary sidebar.
- **Nauta is the ecosystem context.** Present it as compact, source-labelled connected
  intelligence, never as a fictional agent workspace or a competing product shell.
- Use product names only when the operation data provides a real relationship. Any
  non-production record must be visibly labelled by its database source.
- Never present synthetic calls, rates, arrivals, drivers, or documents as live data.

## Foundations

The implemented CSS tokens in `dashboard/src/index.css` are the source of truth.

| Token | Value | Intended use |
| --- | --- | --- |
| `--navy` | `#0B213D` | Brand anchor, sidebar, high-focus action panel, primary ink. |
| `--sand` | `#F8F7F2` | Main application background. |
| `--panel` | `#FFFFFF` | Operational surfaces and readable evidence. |
| `--blue` | `#2A78EA` | In-progress work, navigation links, selected timeline state. |
| `--green` | `#E6FF77` | Primary operator CTA and deliberate focus. |
| `--orange` | `#F4863D` | Urgent exception, denial, or failed recap only. |
| `--sand-deep` | `#D7D4C5` | Quiet dividers and pending timeline marks. |
| `--ice` | `#F2F4FE` | Selected or evidence-adjacent surfaces. |

Do not introduce a second brand palette. New tones should be derived from these tokens
with `color-mix` only when a state needs a quieter surface.

### Typography

- **DM Sans** is the interface typeface: headings, actions, descriptions, and readable
  operational copy.
- **Martian Mono** is reserved for IDs, clocks, timestamps, status badges, source labels,
  and other metadata that benefits from a mechanical, verifiable feel.
- Headings use medium weight, tight tracking, and an occasional blue italic emphasis.
  Do not use oversized display treatment inside dense operational modules.
- Use sentence case for labels and direct verbs for actions: `Start RFQ`, `Request award
  review`, `Open audio evidence`.

## Application composition

### Shell

- Keep the navy left sidebar for product identity and the primary routes: Operations,
  Calls, and Configuration.
- Keep the top bar quiet. It may state data-source status, but it must not compete with
  the operation's current action.
- Operational views do not scroll-snap and must remain usable at normal browser zoom.

### Operations

- Group the queue in this order: **Needs attention**, **Volta is working**, and **In
  execution**.
- Each row must show the operation reference, route, container, current stage, next
  action, free-time state, and source freshness.
- The free-time clock is a decision signal, not a decorative KPI. Use orange only when
  urgency warrants it.
- Empty, loading, unavailable, and source-error states must clearly say what is missing
  and offer a safe recovery action where one exists.

### Operation workspace

The detail view is the product's primary work surface. Preserve this order:

1. Operation identity and free-time state.
2. Source-labelled timeline from arrival through execution.
3. Carrier offer comparison and evidence links.
4. Call evidence and policy decisions.
5. Dominant next-action panel with readiness checks and mandate context.
6. Connected intelligence rail and commitment/execution state.

The timeline is intentionally vertical so every checkpoint remains legible beside the
decision rail. Do not collapse it into an ambiguous progress bar.

### Calls and evidence

- A call is an evidence record, not a chat transcript.
- Keep timestamps, speaker identity, relevant fragments, policy decisions, recap state,
  and the exact evidence pointer together.
- Show an audio link only when the database provides an authorized URL. If no link or
  offset exists, state that verification is unavailable; never imply that a commitment
  is verified without it.
- Original transcript language is immutable evidence and may differ from interface copy.

### Configuration

- Separate presentation preferences from authorization.
- Bot preferences may describe language and recap channel, but they must never suggest
  that they widen authority.
- Display the active immutable mandate, approved FX snapshots, and trusted directory
  identity as read-only evidence.
- Do not add an in-place mandate editor. A policy change creates a new authenticated
  version; the UI should eventually request that workflow rather than mutate fields.

## State language and color

Status always uses text in addition to color.

| State | Treatment | Required language |
| --- | --- | --- |
| Ready / confirmed / committed / resourced / executed | Green-tinted confirmation | State exactly what is confirmed. |
| RFQ open / in progress / award under review / verbal / recap sent | Blue-tinted progress | Explain what remains before commitment. |
| Outside mandate / escalated / denied / recap failed | Orange exception | State the exception and next human action. |
| Pending / unknown / no evidence | Neutral | State what evidence or action is missing. |

`VERBAL` and `RECAP_FAILED` must always state **not booked** or **not committed**. An
award request locks the market; it is not a booking. Only the verified commitment chain
may use confirmed language.

## Interaction rules

- One green primary CTA per decision context. The action panel owns it.
- An action that changes RFQ state requires an explicit confirmation dialog containing
  mandate scope and vetted carrier context.
- Do not create a browser-side control that writes a commitment or its state.
- Keep quote selection and award request separate. A recommended offer is still only a
  recommendation until policy and the verification chain permit a commitment.
- Use links for evidence navigation and secondary review. Do not hide evidence behind
  menus or hover-only controls.

## Data authenticity

- The UI reads backend projections only; it never connects directly to Supabase.
- UI fallback states must not manufacture sample operations. A missing database
  configuration is a visible `503` condition, not an invitation to show fixtures.
- Test doubles belong in test code. Any non-production data used for a deployed demo
  belongs in the database and carries an explicit source label.
- Source freshness and source identity are part of the product, not implementation
  detail. Preserve them when adding or changing a projection.

## Accessibility and responsive behavior

- Use semantic landmarks, headings, lists, buttons, and labels before adding ARIA.
- Maintain text contrast on sand, white, and navy surfaces. Never rely on color alone.
- Preserve keyboard access to queue rows, command dialogs, evidence links, and navigation.
- At widths below 820px, the sidebar becomes compact and detail rails stack below the
  primary workspace. Do not hide critical mandate, urgency, or evidence information.
- At small widths, comparison metrics may stack, but evidence timestamps and statuses
  must remain visible.

## Visual change checklist

Before requesting review for a visual change:

1. Compare against the foundations and state rules in this file.
2. Confirm the primary action remains clear without reading every panel.
3. Confirm urgent, in-progress, confirmed, and failed states remain distinguishable in
   both text and color.
4. Verify desktop and narrow layouts with the local browser.
5. Verify loading, empty, unavailable, and evidence-missing states.
6. Run `npm run build && npm run lint` from `dashboard/`.
7. Update this file in the same PR when a change alters the visual contract.
