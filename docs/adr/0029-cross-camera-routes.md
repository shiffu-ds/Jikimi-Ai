# ADR-0029: Cross-camera routes are scored per site and calibrated per route

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-25
- **Feature / gap:** F2 Tier 2 (G09, G10); results in `docs/results.md` ("Cross-camera routes")

## Context
A scout circles gate -> street -> gate, never stopping long on one camera, so each camera's
loitering plugin sees only short passes. The plan's answer is a trajectory transformer over
segments of a global route. Two problems showed up while building it: the model's camera
embedding only means something for the cameras it was trained on, and scoring the route again
at every new segment is multiple testing - calibrated per prefix length, normal routes were
alerted 2.8 % of the time at alpha = 1 %.

## Decision
- The edge links finished bike tracks across its cameras by appearance (re-ID descriptor, same
  rider count) and the camera graph (no faster than mean - 3 std); segments carry dwell, gap,
  speed, u-turns and time of day, built by one function shared by training and serving.
- From the 3rd segment on two cameras, the route is scored (leave-one-out masked NLL of the
  trajectory transformer, ONNX) and the alert's score is the **running maximum** over the route.
  The calibration set holds one score per normal route (its final running maximum), so a normal
  route raises an alert with probability <= alpha, however often it is re-scored.
- A model knows its cameras (stored next to it); the edge turns cross-camera off when the site's
  cameras are not all in it. One route raises at most one alert (the gate keys on the route).

## Consequences
On synthetic routes: normal routes alerted 0.62 % at alpha 1 %, the guard's own night patrol
0 %, scouts 85 % by the 3rd segment and 97 % by the 4th. Every site needs its own model and
calibration from its own normal routes (pilot); the synthetic ones only bootstrap the demo.
