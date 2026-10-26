# ADR-0034: Personal-safety alerts watch behaviour, never who someone is

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-25
- **Feature / gap:** F23, new (personal safety: phone snatching on foot, warning before an assault,
  parked-bike theft, crowd panic)

## Context
Bike snatching was the only street crime the edge recognised. Owners asked for the other things
guards are expected to stop: phones snatched by someone on foot, and above all a warning *before*
someone is assaulted, not a clip afterwards. "Women safety" analytics usually start by classifying
gender (a lone woman at night, a woman surrounded by men). This project never estimates gender,
age or identity (ADR-0003; the plugin registry refuses them), and for good reasons here too: the
estimate is often wrong, it would not protect anyone it misclassifies, and it invites policing of
who may walk with whom.

No camera can know intent, and nothing can "predict a rape". What a camera can see are the
situations that come before an assault, for anyone: being followed, closed in on by a group,
grabbed, dragged, pushed into a vehicle, knocked down.

## Decision
Four plugins over the same tracks, behaviour only, each with its own calibration set:

- `foot_snatch` (`snatch`, `on_foot: true`): two people who came from apart touch, and within 3 s
  one of them breaks from walking pace into a run away from the other and out of sight; a victim
  holding a phone to the head (pose) raises it. Not: greetings, hand-overs (nobody runs), a jogger
  brushing past (already running), children playing tag (they run before and come back), a crowd
  running (that is `crowd_panic`).
- `person_safety` (`person_in_danger`, `features.pattern`): `following` (keeps a few steps behind,
  stops when they stop, hurries when they hurry; friends walk beside, families come up beside at a
  stop, strangers overtake), `surrounded` (three or more close in from directions at least 120°
  apart within 4 s and the person ends up in the middle; on a circle of friends nobody is in the
  middle, customers arrive one by one), `struggle` (bodies against each other whose velocities keep
  reversing for seconds), `dragged` (moving off together while one is held low or fighting it),
  `forced_into_vehicle` (after that, disappears into a car or rickshaw that leaves at once; plain
  boardings are the everyday units), `fall` (upright to lying within 1.5 s and staying down; lying
  down slowly to sleep is not).
- `vehicle_theft`: a bike parked for a minute or more, someone at it for a long time (crouching),
  another bike waiting nearby with its rider on, then it is ridden or pushed away. The alert asks
  the guard to check whether it is the owner; a stuck lock is the honest hard case.
- `crowd`: many people break into a run within 3 s *away* from a common point (divergence), not
  towards a rickshaw (convergence); a scream or gunshot from the audio plugin adds to it.

Scores are hand-set logistic combinations of interpretable features (like the bike snatch's B1
baseline). The conformal p-value against simulated street life (every everyday look-alike above,
ten minutes at a time) routes them; only moments that could alert are calibration units.
Context changes severity, not the score: urgent patterns (struggle, dragged, forced into a
vehicle, fall) and following / surrounded at night with nobody else around are high once past
LOG_ONLY, so the guard also gets them by SMS when the internet is down. Explanations say what was
seen and what to do (go and ask if they are all right; call 15 after a forced boarding), never who
anyone is, and pass the neutral-wording audit.

## Consequences
Anyone who is followed, cornered, grabbed or knocked down is covered, whatever they look like,
and two people walking together are never an alert. The cost is that these are simulator
heuristics: scripted scenes and hard negatives in `sim/safety.py`, measured in
`docs/results.md`; real performance needs consented footage from a pilot, per-site calibration
and shadow mode first. Real box jitter is larger than the simulator's, which matters most for
`struggle`, so a site's calibration (not the simulator's) must set its thresholds. The on-foot
snatch can use the pose model for every close pair of pedestrians (`person_poses`), which costs
CPU in crowds; without poses it still works from boxes. A stall where customers stand all round
the vendor can be excluded per zone (`person_safety.ignore_surrounded_zones`).
