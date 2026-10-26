# Changelog

## 0.1.0 - 2026-10-24
First runnable version of the Solo-track MVP (plan v2.4).

- Personal safety (F23, ADR-0034, 2026-10-25): four behaviour-only plugins - `foot_snatch`
  (a phone snatched by someone on foot: approach from apart, touch, a run out of sight; phone held
  to the head raises it), `person_safety` (`person_in_danger` with `following`, `surrounded`,
  `struggle`, `dragged`, `forced_into_vehicle`, `fall`: the moments before an assault), and
  `vehicle_theft` (parked bike worked on, waiting accomplice, ridden or pushed away) and `crowd`
  (people scattering from one point). No gender, age or identity is estimated. Each pattern has
  its own calibration set from simulated street life with every everyday look-alike (greetings,
  joggers, children at play, friends and families walking together, customers, boarding,
  resting, owners and stuck locks, running for a rickshaw); night with nobody around raises the
  severity, not the score. Urdu / Roman / English reasons, SMS, Hindi voice, dashboard labels,
  search words, guard guide; 19 new golden cases (46 % hard negatives). Federated learning
  results filled in (F14: FedAvg 0.944 vs pooled 0.954; with three sites differential privacy
  either ruins the model or gives no real guarantee).
- Tier 2 / Tier 3 features (2026-10-25), each measured in `docs/results.md`:
  cross-camera routes with a trajectory transformer and per-route calibration (F2, ADR-0029);
  a deterministic, read-only investigation agent with clip citations and an Analyst chat
  (F1, ADR-0032); VLM verifier (advisory / gate) and a distillation loop with SmolVLM-256M,
  which fails its own test and therefore stays silent (F5/F6, ADR-0030); opt-in mohalla network
  sharing only confirmed incidents as 2-hour embeddings (F21, ADR-0031); Hawkes risk estimate
  and patrol route on the overview (F15); audio events with late fusion and a training tool for
  recordings (F13); FedAvg across virtual sites with optional DP noise (F14); low-light
  enhancement with an ablation that keeps it off (F18); Hindi-voice fallback for Urdu alerts
  (F12, ADR-0033); laptop / USB webcams as camera sources (`webcam:0`, also in the wizard).

- Guard voice replies (F12, ADR-0025): the guard app records a reply, the server transcribes it
  (faster-whisper small int8, VAD, optional `voice` extra) and reads the intent with a shared
  Urdu / Roman / Devanagari / English parser (help > false alarm > seen, clause-aware negation);
  nothing is sent until the guard taps; audio is not stored. SMS free-text replies use the same
  parser. `eval/voice_check.py` (written replies, flite-spoken clips, your recordings).
- Camera re-anchor (F10, ADR-0026): after `moved`, an admin's "accept new view" on the Health page
  (signed `CommandBundle`, run once on the edge, acknowledged in the heartbeat, 24 h expiry) or 10
  minutes standing still makes the current view the reference; low-severity notice. Health page
  also shows the camera's own motion (`moving`).
- Bike colour naming revised on simulator and real crops together (real per-crop 31 % -> 66 %
  with white ~ silver, simulator 72 % -> 81 %, RUVR-sim Recall@10 0.85 / MRR 1.00); infrared
  frames name no colour.
- OpenVINO INT8 without PyTorch (ADR-0027): `scripts/quantize_openvino.py` (NNCF on local clip +
  simulator frames, head decoding kept in float, FP32 comparison and timings); `laptop` profile
  pipeline 254 -> 150 ms per frame on the i5-6200U.
- Setup wizard on the edge (F20, ADR-0028): `jikimi-edge setup` / `make setup-wizard`, Urdu-first
  page behind a one-time PIN: discovery or brand + IP, connection test with blurred preview, zone
  drawing, detector test, save to `.env` (600) and `site.yaml` (comments kept, backups).
- Fixes: Haar face blur no longer crashes on OpenCV 5 (falls back to head blur); audio decoding no
  longer depends on faster-whisper's PyAV call that PyAV 19 removed; the stream test and the wizard
  give up on an unreachable recorder after 6 s instead of FFmpeg's 30 s.

- Edge runtime: simulator + RTSP/file sources, torch-free YOLO decode (YOLO11/YOLO26), ByteTrack,
  rider association, appearance re-ID, loitering / snatch / camera-health / rules plugins,
  split-conformal routing, alert gate with upgrades, Ed25519 signing, SQLite outbox, SMS fallback
  (GSM modem or fake modem), clip recorder with head blur, encrypted originals, power profiles.
- Server: FastAPI, SQLite/PostgreSQL, RBAC + site isolation, hash-chained audit, escalation chain,
  WebSocket live updates, Roman Urdu search, evidence packs (PDF + QR + Merkle + OpenTimestamps),
  public verify portal, SOS, statistics.
- Dashboard + guard PWA (Next.js static export, Urdu RTL default, dark mode).
- ML: two-person ST-GCN, trajectory transformer, PakSnatch-sim synthetic data, evaluation stats.
- Evaluation: golden replay suite, empirical false-alarm measurement.
- Rule builder (F11): Roman Urdu -> rule DSL (clarification questions instead of guesses), site
  validation, 7-day backtest, supervisor proposes / admin approves, signed bundle that the edge pins
  and hot-reloads (ADR-0022); dashboard "Rules" page.
- Event modes (F16): dependency-free Hijri estimates (Ramadan, Chand Raat, both Eids, Muharram
  9-10, 14 August), admin confirmation per site, signed calendar on the edge (same pinned key as
  rules), mode of the day, per-mode calibration with the "kyun?" sentence naming the set used,
  `festival_traffic` simulator scene and `--scenario/--mode` for `calibrate` and `evaluate-fa`
  (ADR-0023); dashboard event-mode card and today's mode on the overview.
- The edge reports its rule/calendar bundle versions and today's mode in every heartbeat, so the
  dashboard shows "running on the edge" for approved rules and the calendar; bundles signed
  before the one already applied are refused (no rollback by replay).
- Conformal validity check (`eval/conformal_validity.py`): P(p <= alpha) <= alpha on held-out units;
  finding: the KS drift monitor does not see a festival rush, so the edge reports bike volume vs
  the calibration and the dashboard suggests confirming an event mode at >= 2x.
- DVR onboarding (F20): ONVIF WS-Discovery, GetCapabilities/GetProfiles/GetStreamUri with a
  WS-Security digest (checked against the ONVIF guide's example), RTSP templates for Hikvision /
  Dahua / CP Plus / Uniview / TP-Link with masked passwords, `discover` and `probe-stream` commands.
- Real footage (`eval/footage_check.py`, YOLO11n + pose as ONNX on a public junction clip) found
  6 more issues, all fixed: sticky riders through association flicker, same-depth gate for snatch
  pairs, per-second camera ego-motion status that keeps snatch/loitering out of ALERT_NOW while the
  camera moves, head blur above every two-wheeler, pose model only when a pedestrian is in reach
  (2× faster), ST-GCN inference windows aligned with training (`CONTACT_SPAN`).
  `eval/shadow_snatch.py` compares B1 and ST-GCN in the pipeline.
- Fixes found while testing the running system: MTTA of SMS acks synced after an outage (was
  negative), one seed per camera in `calibrate` / `evaluate-fa` (the same scene was counted twice),
  snatch contact must last > 1 frame (`min_close_s`), evidence stays verifiable after a server key
  rotation (`python -m jikimi_server retire-key`).
- Dashboard unit tests (vitest, in CI): the verify portal's pure-JS SHA-256 against FIPS vectors and
  node:crypto on every padding boundary, Urdu/English string parity; the fallback no longer needs
  `window`. ST-GCN reports carry an episode-level bootstrap CI; `evaluate-fa` reports the 95 %
  Poisson upper bound; `eval/shadow_snatch.py` compares B1 and ST-GCN on the same pairs.
