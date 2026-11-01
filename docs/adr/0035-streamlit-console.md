# ADR-0035: The front end is a Streamlit console, written like a duty register

- **Status:** accepted · supersedes ADR-0020 (static Next.js dashboard)
- **Date:** 2026-11-01

## Context
The first front end was a Next.js static export with a guard PWA. It worked, but it was a second
language and toolchain (TypeScript, npm, generated contract types) in a project whose people and
code are Python, and its look — tiles, icons, gradients — read like every other generated
dashboard. The site owner asked for the front end in Streamlit, with a human feel.

## Decision
`apps/console` is a Streamlit app that talks to the existing REST API with the signed-in person's
Bearer token; nothing on the server changed except that it no longer serves a dashboard.

- **Look:** a guard-room *roznamcha*: warm paper, ink, ruled rows with serial numbers, rubber-stamp
  statuses in Urdu (کھلا، دیکھ لیا، غلط الارم), Urdu headings in Nastaliq, the overview written as a
  sentence ("Aaj ab tak 4 alert aaye…") instead of KPI tiles, and a handover note between shifts.
- **Pages by role:** supervisors and admins get the overview, register, live cameras, search and
  the investigation agent, evidence, rules and event modes, camera health; guards get *Meri duty*
  (one big card, three buttons, voice reply, SOS) at a phone's width; the evidence check is public.
- **Live:** `st.fragment(run_every=…)` refreshes the register, the guard card and the camera
  snapshots; alert details open in a dialog with the signed clip, the reason and the timeline.
- Contract types for TypeScript are gone; OpenAPI (`/docs`) is the shared description.

## Consequences
One language and one toolchain (`uv sync`), and pages that look made for this guard room. What
was lost: the installable PWA (home-screen icon, offline queue, service worker) and push-style
alarms on a locked phone — the guard view needs the browser open, and SMS remains the fallback
when it is not. A browser reload signs the person out (Streamlit keeps the session per tab).
