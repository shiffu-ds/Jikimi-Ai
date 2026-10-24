# Results (v0.1, simulator) — and how to reproduce them

> **Read this first.** Every number here comes from the **simulated** cameras in `edge/.../sim`
> (synthetic CCTV scenes with scripted events and random background traffic) on the development
> laptop (Intel i5-6200U, 2 cores / 4 threads, 12 GB RAM, Kali Linux). They show that the pipeline,
> statistics and offline paths work end to end. They are **not** accuracy claims about real
> streets: those need the consented PakSnatch / PakRoads data and a pilot (plan Section 14.6).

## End-to-end behaviour

| Check | Result | Reproduce |
|---|---|---|
| Golden replay (7 scenario types × seeds = 18 runs; 8 runs are hard negatives) | **18/18 pass**: loitering ALERT_NOW at the 2nd pass (66 s), snatch ALERT_NOW day and night (33.4 s), tamper (48 s), 0 alerts on all 8 hard-negative runs | `make replay` |
| Snatch, day and night: event → ALERT_NOW | ~3.4 s after the grab (p ≈ 0.0005) | `python -m jikimi_edge replay --scenario snatch_basic --camera cam-street-02` |
| Loitering early warning | ALERT_NOW at the 2nd pass with a slow-down (~45 s after the 1st pass), before any incident | `... --scenario loiter_basic` |
| Hard negatives (delivery hand-over, asking directions) | no alert | `... --scenario delivery_drop` / `asking_directions` |
| Camera covered | tamper ALERT_NOW after 8 s | `... --scenario camera_cover` |
| Camera turned on purpose ("moved" would never clear) | an admin's "accept new view" (signed command, run once even across restarts) or 10 min standing still in the new position makes it the reference; a low-severity notice says to check the zones | `pytest edge/tests/unit/test_perception.py -k moved`, `server/tests/test_commands.py` |
| Edge → server alert latency (laptop, live demo) | 0.8–1.0 s | alert timeline "edge→server" chip |
| Internet down → SMS | live demo: snatch alert E895 → Roman Urdu SMS **5.0 s** later (plan target < 20 s) | `make net-cut`, `data/edge/sms/outbox.jsonl` |
| SMS reply "1 CODE" while offline → ack synced | reply recorded offline; after `make net-restore` alert + ack reached the server within 0.1 s of the link coming up, actor `sms:+92…`, MTTA counted from the SMS | `make sms-reply TEXT="1 E895"`, `make net-restore` |
| Power cut (`kill -9` while writing) | 0 committed alerts lost (3 cut points) | `pytest -m chaos eval/tests` |
| Evidence: 1-bit change in clip or PDF | verification fails (clip check / file match) | `server/tests/test_api.py::test_evidence_pack_verify_and_tamper` |
| All server tests (API, rules, calendar, commands, voice, VLM flow, hotspots, network, agent, search, end-to-end edge sync) on PostgreSQL 16 + pgvector 0.8.7 | **81/81 pass** (same suite as SQLite) | `JIKIMI_TEST_DATABASE_URL=postgresql+psycopg://... pytest server/tests` |

## Calibrated alerting (F7)

Calibration: simulated normal traffic incl. delivery and directions stops (4 camera-hours, a
different scene on each camera).

| Plugin | Calibration units | Units / camera-hour | p99 normal score | Worst case at α = 0.01 |
|---|---|---|---|---|
| Loitering (bike entities) | 1,371 | ~343 | 0.333 | 3.4 FA/h |
| Snatch (bike–pedestrian pairs) | 2,046 | ~512 | 0.371 | 5.1 FA/h |

The worst case is why the plan's "α = 0.01" alone cannot meet "< 0.1 FA/camera-hour"
(ADR-0021). With candidate gating (≥ 2 passes; real hand contact) the **empirical** rate on
held-out simulated normal traffic (different random seeds) is:

| Run (held-out normal traffic; each 10 min has a delivery and a directions stop) | Camera-hours | ALERT_NOW false alarms | FA / camera-hour | 95 % upper bound |
|---|---|---|---|---|
| before the testing fixes (same seed on both cameras, single-frame "contact" accepted) | 2, really 1 independent | 2 = one drive-by counted twice | 1.0 | – |
| after (one scene per camera, contact must last > 1 frame), seeds 50000–50059 | 10 | **0** (and 0 VERIFY) | **0.0** | 0.30 |
| + 20 more camera-hours, new scenes (seeds 50060–50179) | 20 | **0** (and 0 VERIFY) | **0.0** | 0.15 |
| **all held-out hours together** | **30** | **0** | **0.0** | **0.0999 — below the plan's 0.1** |

`python -m jikimi_edge evaluate-fa --hours 10` (add hours with new scenes: `--hours 20 --seed0 50060`).
Zero events only bound the rate: 95 % < 3 / camera-hours (rule of three); 30 clean camera-hours is
the least that shows the plan's < 0.1 FA/camera-hour, and that is what was measured — on simulated
traffic. Real footage brings failure modes the simulator did not have (next section).

Is the guarantee real? Calibrate on the first half of a set's runs, score the second half (other
scenes): split-conformal p-values must satisfy P(p ≤ α) ≤ α. `python -m eval.conformal_validity`

| Set (held-out half) | P(p ≤ 0.01) | P(p ≤ 0.05) | P(p ≤ 0.1) | P(p ≤ 0.2) |
|---|---|---|---|---|
| Snatch, ordinary days | 0.006 | 0.031 | 0.067 | 0.179 |
| Snatch, festival (its own set) | 0.008 | 0.043 | 0.087 | 0.183 |
| Loitering, ordinary days (many tied scores → conservative) | 0.009 | 0.009 | 0.009 | 0.009 |
| Loitering, festival (its own set) | 0.008 | 0.030 | 0.030 | 0.030 |

Valid everywhere. The KS drift monitor stays quiet between two halves of ordinary days (p = 1.0
loitering, 0.51 snatch), as it should, but it does **not** flag the festival rush either (p = 0.048 /
0.093 against its α = 0.01): per-unit scores barely change on a festival day; what changes is the
volume (2.2× loitering units, 4.6× bike–pedestrian pairs per hour) and the loitering tail (p99 0.33 →
0.49). So the drift monitor cannot replace the event calendar (F16). The edge therefore also reports its
bike volume against the calibration's units/hour in every heartbeat, and on a "normal" day at ≥ 2×
the dashboard asks the admin to confirm an event mode (`test_volume_is_reported_against_the_calibration_rate`,
`test_rush_hint_from_edge_volume`).

## Search (F1)

| Check | Result |
|---|---|
| Parser test cases (spelling variants, Urdu script, riders/helmet, 11 time phrases, privacy) | 33/33 |
| Lexicon variants (exported for RUVR) | 365 |
| Query parse + retrieval on the demo index | ~15 ms |
| **RUVR-sim** end to end: 8 simulated scenes through the real edge and server (1,040 indexed tracks, 422 bikes with scripted ground truth), 61 queries (colour; colour + riders; Urdu script), 2–3 spellings each | Recall@10 **0.85** [0.81, 0.89], MRR **1.00** [1.00, 1.00]; colour-only queries 0.90; Urdu script 0.93 / 1.00 (colour namer v2.4; v0.1 namer: 0.86 / 0.975) |
| Spelling robustness | every spelling of a query returns the same ranking; the misses come from vision, e.g. *"silver bike 2 sawar"* Recall@10 0.3 (silver vs white, rider count) |
| A colour rule tuned only on real crops (riders masked everywhere) | Recall@10 fell to **0.49**, MRR 0.66: in the simulator riders cover blue / green bodies, which vanished. The shipped rule (below) was chosen on simulator and real crops together |

`python -m eval.ruvr_sim --scenes 4` (CIs: bootstrap over queries).

## Rule builder (F11)

| Check | Result | Reproduce |
|---|---|---|
| Roman Urdu / Urdu-script rules understood (schedules incl. "subah 9 se 5 tak", counts, colours, days, severity, who to notify) | 9/9 | `pytest server/tests/test_rules.py` |
| Unclear input → clarification question, never a guess (no place, unknown zone, "11 baje" without subah/raat, no condition) | 4/4 | same |
| Backtest on 7 days of tracks | exactly the 1 qualifying track of 4 (time window, dwell, object) | `test_rule_lifecycle_backtest_approval_and_signed_bundle` |
| Unapproved rule in the edge bundle | never; supervisor cannot approve (403) | same |
| Tampered / other-key / other-site / unapproved bundle on the edge | refused | `pytest edge/tests/unit/test_rules_edge.py` |
| Approved rule on the live pipeline (`loiter_basic`: a person waits ~3.5 min at the gate) | fires once, high severity, guard + supervisor; disabling removes it | same |
| End to end, no fakes: real API signs → real edge sync agent pulls over HTTP → pipeline | rule lands only on its camera; Chand Raat mode active; pinned key = server key | `pytest server/tests/test_edge_sync_e2e.py` |
| Dashboard knows when a rule / the calendar is running on the edge | from the bundle versions in the edge heartbeat | `test_dashboard_sees_when_rules_and_calendar_reach_the_edge` |

## Event modes (F16)

| Check | Result | Reproduce |
|---|---|---|
| Hijri estimates vs the real Pakistani dates of 2024-25 | exact for both Eids and Ashura; start of Ramadan 1 day early (moon sighting) | `pytest packages/jikimi-common/tests -k Hijri` |
| Admin confirms → signed calendar → mode of the day on the edge (Chand Raat inside Ramadan) | works; other-key calendar refused | `pytest server/tests/test_calendar.py edge/tests/unit/test_rules_edge.py` |
| "kyun?" sentence names the set that produced the p-value | "Chand Raat ko …" with its own set, "aam dinon mein …" on fallback | same |

Festival rush in the simulator (`festival_traffic`: 2.2× traffic, bikes slowing in the crowd 3× as
often, extra deliveries and directions stops), same held-out scenes for both rows:

| Calibration answering on the festival scenes (seeds 50000–50011) | Camera-hours | ALERT_NOW false alarms | 95 % upper bound | Loitering ALERT_NOW line (α = 0.01) |
|---|---|---|---|---|
| ordinary days (`--mode normal`) | 2 | 0 | 1.5 / h | score 0.333 |
| Chand Raat's own set (`--mode chand_raat`) | 2 | 0 | 1.5 / h | score 0.485 |

Neither set raised a false alarm on these 2 camera-hours: the candidate gates (≥ 2 passes, contact
> 1 frame) already hold. What the mode moves is the line: a loitering score of 0.47, the size of the
demo's real early warning, is ALERT_NOW on an ordinary day and not on Chand Raat, where a bike
circling slowly is ordinary. One snatch false alarm (score 0.79) did appear in the festival
*calibration* scenes under the ordinary-day set; it would fire under the Chand Raat set too (its p99
is 0.36): for snatch the rush changes the volume (4.6× pairs per hour), not the score distribution,
which is also why the volume hint above exists. Showing an FA difference needs more festival hours.

## Guard voice replies (F12)

The guard says *"haan dekh liya"*, *"ghalat alarm hai"* or *"madad chahiye"*; the server
transcribes it (faster-whisper small, int8, CPU), `jikimi_common.intents` reads the intent, and
the guard app shows both and sends nothing until the guard taps (ADR-0025). The same parser now
also reads free-text SMS replies in Roman or Urdu script.

| Check | Result |
|---|---|
| 102 written replies (Roman Urdu, Urdu, Devanagari, English; 32 seen, 29 false alarm, 30 help, 11 unclear), **first run** | 95/102 = **93.1 %**; all 7 misses were "ask again", none a wrong action; 2 were help requests (*"jaldi kisi ko bhejo"*, *"backup chahiye"*) |
| Same set after adding the words those misses showed and fixing a double negative (*"nahi bhai kuch nahi"*) | 101/102 (in-sample, so an upper bound); 0 help missed; 0 unclear replies acted on |
| 6 English replies spoken by ffmpeg's flite voice; pink noise; silence | 6/6 right intent; noise and silence → empty text (VAD), no intent |
| Speed on the i5-6200U | model load ~2 s (warm disk), **4.3–5.4 s** per 1–2 s reply; beam 1 vs 5 and 2 vs 4 threads made no difference (the encoder dominates) |
| Urdu speech (the plan's test: 200 guard recordings, Whisper WER, intent ≥ 90 %) | **not yet**: no recordings. `python -m eval.voice_check --audio DIR` scores files named `<intent>__*.webm` |

`make voice` (report: `eval/reports/voice_check.json`).

## DVR onboarding (F20)

| Check | Result | Reproduce |
|---|---|---|
| WS-Security password digest | equals the ONVIF Application Programmer's Guide example | `pytest edge/tests/unit/test_onboarding.py` |
| WS-Discovery reply, GetCapabilities → GetProfiles → GetStreamUri (spec-shaped replies, mock HTTP) | streams found largest first; faults ("not Authorized") raised; password never sent in clear | same |
| RTSP templates (Hikvision, Dahua, CP Plus, Uniview, TP-Link) | credentials URL-quoted, masked on screen | same |
| Stream test on a video file | resolution, frames, failed reads, advice | same |
| Setup wizard (`make setup-wizard`, Urdu page served by the edge, PIN): find → connection test + preview → draw zone → detector test → save | end to end through its HTTP API on a video file; camera block added to `site.yaml` with all comments kept, RTSP URL (password URL-quoted) only in `.env` (mode 600), both backed up; 5 wrong PINs lock it for 60 s | `pytest edge/tests/unit/test_setup_wizard.py` |
| Wizard on the junction clip (i5-6200U, INT8 detector) | connection test + preview 3.2 s ("heavier than 720p: use the sub-stream"), detector test 0.8 s (11 people, 5 motorcycles, 1 car; riders' heads blurred) | `Wizard.probe / detect` |
| Against a real recorder; "non-technical user adds a camera in < 10 min" (plan target) | **not yet** — first pilot site | `python -m jikimi_edge discover`, `make setup-wizard` |

## Snatch model (F3) — PakSnatch-sim pre-training

Data: 8,904 two-person windows (3.2 s resampled to 32 frames) from 600 synthetic episodes, built
with the *same* pair-building and input code the edge runs (`build_samples`, `build_input`), so
training and serving cannot drift apart. Split by episode: train 5,972 / val 1,704 / test 1,228
windows (384 positive test windows). Two-person ST-GCN, focal loss, AdamW + cosine schedule, early
stop on validation AUC. Intervals resample whole episodes (windows of one episode are correlated).

| Metric (held-out episodes) | Value |
|---|---|
| Validation AUC (best of 25 epochs, epoch 19) | 0.983 |
| Test AUC, 95 % CI resampling episodes (68 episodes, 1,228 windows, 384 positive) | **0.978 [0.966, 0.989]** |
| Precision at recall 0.8 | 0.926 |
| Expected calibration error | 0.055 |
| ONNX export vs PyTorch | same test AUC from the ONNX file (`evaluate_stgcn`) |

Inside the edge plugin, on the same 294 bike–pedestrian pairs of 26 golden scenes (16 real
snatches), `make shadow`:

| Scorer | AUC | Lowest real snatch | Highest other pair | Highest hard negative (delivery, directions) |
|---|---|---|---|---|
| B1 heuristic (default) | 1.00 | 0.947 | 0.783 | 0.312 |
| ST-GCN, window cut when the pair is released (before the fix) | 1.00 | 0.508 | 0.499 | 0.493 |
| ST-GCN, windows around the closest approach as in training (after) | 1.00 | **0.960** | 0.836 | 0.592 |

The first ST-GCN row was a train/serve mismatch: training labels a window positive only when it
ends within 4 samples of the closest approach, but the plugin scored the window cut after the bike
had gone, which training had called negative. Both now use `CONTACT_SPAN`. B1 stays the default:
it still keeps hard negatives lower (its long-stay term), and the ST-GCN has only seen synthetic data.

## Throughput on the laptop

| What runs per frame | ms / frame | Cameras at 5 fps on the i5-6200U |
|---|---|---|
| Simulator (tracks given, rendering included), `make bench` | 19 (51.7 frames/s) | 10.3 |
| Real video, YOLO11n FP32 ONNX 640 px + YOLO11n-pose, pose on every frame with riders | 455 (detector 174, pose 255) | 0.4 |
| Real video, pose only when a pedestrian is within reach of a bike (`pairs_in_reach`) | 218–253 (detector 153–179; pose on 15 of 94 frames) | 0.8–0.9 |
| Same, OpenVINO INT8 (`laptop` profile, below) | **150** (detector 95, pose 93) | **1.3** |

With FP32 ONNX this laptop handles about one camera, with INT8 OpenVINO one and a bit; two
cameras need 3 fps each or a smaller input — measure with `eval.footage_check`.

## OpenVINO INT8 (`laptop` profile)

`scripts/quantize_openvino.py` turns the ONNX models into OpenVINO INT8 with NNCF, without PyTorch
or a dataset download: 195 calibration frames from the junction clip and five simulator scenes
(day and night), 195 *other* frames of the same sources for validation. The YOLO head's box and
keypoint decoding stays in floating point. "vs FP32" = the INT8 model's boxes against the FP32
ONNX model's (IoU ≥ 0.5, same class) at confidence 0.3.

| | Detector (YOLO11n) | Pose (YOLO11n-pose) |
|---|---|---|
| Size: ONNX FP32 → INT8 | 10.7 → 2.8 MB | 11.8 → 3.1 MB |
| Recall / precision vs FP32 | 0.960 / 0.934 | 0.905 / 0.995 |
| Mean IoU of matched boxes; keypoint shift | 0.955 | 0.961; median 0.8 px |
| ms per inference: onnxruntime FP32 / OpenVINO FP32 / OpenVINO INT8 | 102 / 86 / **76** | 158 / 120 / **100** |

The i5-6200U has AVX2 but no VNNI, so INT8 gains less here than on newer CPUs; most of the
pipeline's 1.7× comes from OpenVINO itself. On the junction clip the INT8 pipeline found the same
bikes (10 vs 11 tracks, riders and colours alike) but raised **one VERIFY snatch** (p = 0.022, not
ALERT_NOW) that FP32 did not: a 0.4 s rider-wrist / pedestrian overlap with no getaway (departure
0.07, pedestrian jerk 0.02). VERIFY goes to the verifier / review queue, not to the guard; it is a
reason to run the first pilot weeks in shadow mode with this profile.

`uv run python scripts/quantize_openvino.py` (report: `eval/reports/openvino_int8.json`), then
`python -m eval.footage_check <clip> --profile laptop`.

## Real footage check

A free Pexels clip ("Busy urban traffic with motorcyclists at intersection", 19 s, 1080p60, Pexels
License) of a crowded junction, filmed from inside a car — not a CCTV view, which is useful in
itself: `python -m eval.footage_check data/footage/<clip>.mp4 --profile onnx-cpu` (YOLO11n +
YOLO11n-pose exported to ONNX). The clip has no incident, so every alert on it is a false alarm.

| Check | First run | After the fixes it led to |
|---|---|---|
| Detection / tracking (94 frames at 5 fps) | 746 person, 403 motorcycle, 104 car detections; 11 bike, 6 person, 2 car, 1 truck tracks; riders 8× one, 3× two | same |
| Snatch false alarms | **3** ALERT_NOW | **0** (simulated snatches still ALERT_NOW at 33.4 s) |
| Why 2 of them: riders squeezed between bikes dropped out of rider association for a frame and became "pedestrians" | | `RiderMemory`: a person associated in ≥ 40 % of their frames stays a rider |
| Why the 3rd: a person far *behind* a bike touching it in the image (height 0.08 vs bike 0.25) | | `same_depth`: victim and bike must have the scale of the same distance |
| Camera moving (handheld / vehicle) | only "moved" (vs a reference that never re-learns after a knock) | new per-second ego-motion status `moving`; snatch / loitering are kept out of ALERT_NOW while it is on |
| Heads blurred | only detected persons; many riders never detected | also a head band above every two-wheeler (`rider_head_proxy`); riders behind a car (bike not detected) and tiny people on a footbridge are still missed |
| Speed | 455 ms / frame | 218–253 ms / frame (pose gated) |
| Bike colours (per track, majority of per-frame names) | all 11 "black" | 2 silver (both light scooters), 1 red (red), 8 black: by eye 7 clearly right, 3 two-tone (black with white / red panels) named black, 1 wrong (a light-grey scooter split 9:9 black / silver) |
| Bike colours (per crop, 32 hand-labelled crops; simulator: 229 crops) | real 31 % (all black); simulator 72 % | real **66 %** if a white bike named silver counts (34 % exact: in this hazy clip white bikes are no brighter than the simulator's silver ones); simulator **81 %** |
| Camera health | moved: warn (correct: handheld) | moving: ok most seconds (drift ~1 %/s, below the 2 % threshold); a moved camera's new view can now be accepted |

The colour rule now: a chromatic colour needs clearly saturated, visible pixels (S ≥ 140, V ≥ 60)
in the lower body band (riders' jackets sit higher); otherwise white / silver / black compares
light against dark pixels with the riders' upper bodies masked out; "white" needs V ≥ 200; an
infrared (grayscale) frame names no colour. Settings were chosen on both sets at once, which are
small and partly in-sample: re-check on each pilot site's footage.

## Tier 2 and Tier 3 features (v2.4)

All of these run in the product; most are measured on synthetic data, because the real data (the
site's routes, incidents, recordings, night footage) only comes with a pilot. Each table says so.

### Cross-camera routes (F2 Tier 2, ADR-0029)

Trajectory transformer (2 layers, d 64) trained self-supervised on 7,230 synthetic normal routes
of a 3-camera site (passing through, deliveries, shoppers, residents, the guard's night patrol);
scored on new routes. `python -m jikimi_ml.train.train_trajectory`.

| Check | Result |
|---|---|
| Normal routes alerted at alpha = 1 % (calibrated per route, running maximum) | **0.62 %** of 487 (first version, calibrated per prefix: 2.8 % - not valid) |
| The guard's own night patrol (it circles too) | 0 % of 300 |
| Scouts circling gate <-> street, alerted by their 3rd / 4th / 6th segment | **85 % / 97 % / 99 %** |
| AUC scout vs normal (whole route) | 0.999 |
| On the edge | one alert per route (`edge/tests/unit/test_cross_camera.py`); golden replay still 18/18 |

### VLM verifier and distillation (F5, F6, ADR-0030)

SmolVLM-256M (Apache-2.0, 513 MB) on the laptop CPU, `python -m eval.vlm_check`: labelled
simulator frames (18 snatch, 37 hard-negative / normal / real-clip frames; 6 covered + 6 clear
camera frames).

| Check | Result |
|---|---|
| Snatch, A/B question (both orders) / yes-no question | AUC **0.40** / 0.27 (worse than chance) |
| Camera covered, A/B / yes-no | AUC **0.53** / 0.08 (a first run on 8 frames gave 1.0: a small-sample fluke) |
| Speed | ~4 s per frame and question; A/B in both orders ~8-11 s |
| Types the server lets it judge (AUC >= 0.8) | **none** - it stays silent rather than mislead |
| Distillation round: 48 teacher calls on uncertain windows | all 48 below 2/3 agreement: no labels, student unchanged (AUC 0.978) |
| Same round with the simulator's true labels for the 48 windows (a perfect teacher) | AUC 0.978 -> 0.973, ECE 0.055 -> 0.036: the gate (AUC must not drop) **rejects** it - 48 labels do not improve a model already at 0.978 on this data |

### Investigation agent (F1 Tier 2, ADR-0032)

`python -m eval.agent_check`: 64 synthetic bike sightings over three nights on two cameras, five
loitering alerts; 48 scripted multi-turn tasks.

| Kind | Result |
|---|---|
| find ("kal raat kaali bike 2 sawar gate pe") | 13/13 |
| follow ("ye bike aur kahan dekhi gayi?") | 10/10 |
| clip ("doosra clip dikhao") | 10/10 |
| count ("kitni laal bike": distinct bikes, exact matches only) | 10/10 (first version counted sightings: 8/10) |
| report ("report banao": draft only) | 5/5 |
| Tool calls per turn | 1.0 (limit 8); every answer cites clips; a forged context is ignored |

The first run scored 45/48: three "failures" were the bike's own alert ranked first, which the
check wrongly rejected; the check was corrected, not the agent.

### Hotspots and patrol (F15)

Hawkes process per zone, `python -m eval.hotspot_check`: incidents simulated from a known process
(hourly base rates + follow-ups, alpha 0.25, ~6 h), fitted on 60 days, asked every 4 h of the next
30 days where to look.

| Site | Share of next-4-h incidents in the top-2 zones: true intensity / **fitted** / hour-of-day history / busiest zones | Reached by a 30-min patrol from the gate |
|---|---|---|
| Quiet (1.4 incidents/day) | 0.56 / **0.54** / 0.42 / 0.40 | 0.88 / **0.84** / 0.74 / 0.86 |
| Busy market (6.4/day) | 0.50 / **0.41** / 0.42 / 0.39 | 0.86 / **0.86** / 0.85 / 0.85 |

Fitted alpha 0.3 and decay 6 h (truth 0.25 and 6 h). It helps most where incidents are few and
clustered; in the busy market it matches the simpler baselines. The dashboard calls it a "risk
estimate", not a prediction.

### Mohalla network (F21, ADR-0031)

| Guardrail | Tested |
|---|---|
| Opt-in needs a recorded written agreement and the site's location | `server/tests/test_network.py` |
| Shares only reviewed-true, high-severity incidents; embedding + riders + colour, no image | same |
| Only to opted-in sites within both radii; never back to the sender; signed bundle | same |
| Expires after 2 h (deleted); embeddings kept 24 h, only at opted-in sites, outside the signed alert | same + `edge/tests/unit/test_network_edge.py` |
| Opting out withdraws this site's shares at once; every share audited | same |
| Neighbour's edge: one medium "watch, do not act" alert per share, its own guard only | `test_network_edge.py` |

### Federated learning (F14)

PENDING_F14

### Audio events (F13)

Pipeline only: log-mel (YAMNet-shaped) -> small CNN -> noisy-OR fusion with a muzzle-flash and a
"crowd running" cue; firecrackers are their own class. No public data has firing *and* screams
under a usable licence, so the classifier must be trained on recordings (`python -m
jikimi_ml.train.train_audio --data data/audio`). On synthetic toy sounds (plumbing only): 5-fold
accuracy 0.79, firecrackers called firing 0 %. That number says nothing about real sound.

### Low light (F18)

`python -m eval.lowlight_check`: 38 junction-clip frames (last 20 % of the clip), darkened at three
levels; reference = the detector's 498 objects on the original frames.

| Found again | dusk | night | dark |
|---|---|---|---|
| No enhancement | 0.56 | 0.25 | 0.07 |
| CLAHE (14 ms) | 0.56 | 0.25 | 0.06 |
| Zero-DCE++ trained on local frames (113 ms) | **0.25** | 0.02 | 0.00 |

Zero-DCE++ brightens so much that it multiplies the sensor noise; CLAHE looked like +0.10 on the
frames it was chosen on and changes nothing on new ones. So the enhancer ships **off** until a
site's real night footage shows a gain (synthetic darkness has no infrared, glare or blur).

### Alerts read aloud (F12, ADR-0033)

Every alert type's Roman Urdu text converts to Devanagari with no Latin letter left (a test per
type), so a phone's Hindi voice reads it as Urdu when there is no Urdu voice.

## Test suite

| Suite | Result |
|---|---|
| Python fast suite (`pytest -m "not slow and not chaos"`) | 273 pass |
| Golden replay (`make replay`) | 18/18 |
| Chaos (power cut, `kill -9`) | 3/3 |
| Server tests on PostgreSQL 16 + pgvector | 81/81 |
| Dashboard (vitest: SHA-256 fallback, Urdu/English parity) | 6/6 |
| ruff, mypy --strict (shared packages), tsc, contract drift, production build | clean |
