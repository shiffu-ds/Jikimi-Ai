# ADR-0024: Gates learned from real footage (riders, depth, moving camera, blur, pose)

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-24
- **Feature / gap:** F3, F10, F19; results in `docs/results.md` ("Real footage check")

## Context
The simulator never showed a crowded junction. On a 19 s public clip of one (filmed from a car), the
edge raised three snatch ALERT_NOWs and left many riders' faces unblurred, at 455 ms per frame on
the laptop. Each failure had a specific cause: riders dropping out of rider association for a
frame, a person far behind a bike touching it in the image, a camera that was itself moving,
blur that only follows detected persons, and the pose model running on every frame with a rider.

## Decision
- **Sticky riders:** a person associated with a bike in >= 40 % of their frames stays a rider
  (`RiderMemory`). A victim is associated for a frame or two at contact at most.
- **Same depth:** a snatch pair needs the person's height to be 0.6-4x the bike box height, i.e.
  the scale of the same distance. (The feet line is not used: it fails on the simulator's geometry.)
- **Moving camera:** the camera-health plugin measures ego-motion between checks 1 s apart (ORB +
  RANSAC partial affine; the background is the largest consistent set). While 2 of the last 3
  checks exceed 2 %, snatch and loitering go to LOG_ONLY: image speeds are not the people's own.
  This is separate from `moved`, which compares with a reference view.
- **Blur above two-wheelers:** besides each person's head, the band where riders' heads are above
  every two-wheeler is blurred (`rider_head_proxy`); over-blurring background is the safe side.
- **Pose only in reach:** the pose model runs only when a pedestrian at the same depth is within
  2x reach of a bike with riders (`pairs_in_reach`).

## Consequences
On the clip: 3 false alarms -> 0, all 18 golden runs still pass (simulated snatches still alert at
33.4 s), 455 -> ~220-250 ms per frame. Costs: a real snatch filmed by a shaking camera is only
logged; a pedestrian who rode pillion earlier in the same track stays a "rider". Still open: riders
whose bike is hidden (behind a car) are not blurred.

**Update (v2.4, same day):** bike colour naming was revised on simulator and real crops together
(results: "Real footage check"); camera re-anchoring after `moved` is ADR-0026.
