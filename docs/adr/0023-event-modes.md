# ADR-0023: Event modes: Hijri estimates, admin confirmation, per-mode calibration

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-24
- **Feature / gap:** F16, G13, plan Section 8.16

## Context
On Chand Raat a market has twice the traffic and bikes keep slowing next to people. Against an ordinary day's calibration set that is "unusual" all evening, so the conformal p-values, and the false-alarm guarantee, would be wrong exactly on the days that matter most. The plan asks for a `calendar_events` table, Hijri dates "from a library", admin confirmation after moon sighting, and a calibration set per mode, but not for how the mode reaches the edge, and the `calendar_events` table had no site.

## Decision
- **Estimates without a dependency:** the arithmetic Hijri calendar (Reingold & Dershowitz). On the 2024-25 Pakistani dates it is exact for both Eids and Ashura and one day early for the start of Ramadan (`packages/jikimi-common/tests`). Estimates are computed on the fly and never stored.
- **Admin confirms:** an admin fixes the dates after the moon is sighted and confirms; only confirmed windows (`mode_windows`, per site, with `confirmed_by`, in the audit log) count. Sites add their own (e.g. a Sunday bazaar).
- **Signed calendar on the edge:** `/v1/edge/calendar`, signed with the server key and checked against the same pinned key as the rule bundle (ADR-0022). The edge stores it and keeps working offline.
- **Mode of a day:** site-local date; the shortest covering window wins (Chand Raat inside Ramadan); otherwise the config default (`normal`).
- **Rush hint:** measured, the KS drift monitor does not notice a festival day (per-unit scores barely change; the volume and the loitering tail do). The edge reports bike volume against the calibration's units/hour in each heartbeat, and the dashboard asks for a mode at >= 2x on a "normal" day.
- **Calibration per mode:** p-values use that mode's set when it exists and fall back to `normal` when it does not. The alert records which set answered (`features.calibration_mode`), and the "kyun?" panel says so: "Chand Raat ko 0.1% se kam" vs "aam dinon mein 0.1% se kam".

## Consequences
Busy days get their own baseline once a site has calibrated them (`python -m jikimi_edge calibrate --scenario ... --mode chand_raat`, on real footage 48-72 h of that event). Until then, alerts on those days are compared with ordinary days and say so. A forgotten confirmation leaves the day in `normal` mode: more alerts on a busy day, never fewer.
