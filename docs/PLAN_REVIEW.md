# Plan review: IMPLEMENTATION_PLAN v2.3 → v2.4

> Ye document `IMPLEMENTATION_PLAN.md` (v2.3, 3,534 lines, 25 sections) ka tafseeli jaiza hai: kya
> mazboot hai, kahan andar se ek doosre se takraata hai, kya ghalat tha, aur v0.1 implementation mein
> har masle ka kya hal kiya gaya. Tamam tabdeeliyan `docs/IMPLEMENTATION_PLAN.md` (v2.4) mein lag
> chuki hain; original file `~/IMPLEMENTATION_PLAN.md` ko chheda nahi gaya.

## 1. Khulasa

**Plan bahut mazboot hai.** Masla sahi chuna gaya (mid-market sites jahan Safe City nahi pahunchti),
competitor/gap analysis imaandaar hai ("public info mein nahi mila"), Tier system aur kill criteria
scope ko control karte hain, aur evaluation/statistics ka hissa (bootstrap, Wilson, rule of three,
fairness slices) aksar professional projects se behtar hai. Maine plan ke hisaab-kitaab dobara
check kiye: weighted scores, Advanced/Professional index, tier effort (131 / 195 / 227 pd), solo
estimates (76 / 55 / 61 pd), Wilson CI (85/100 → 0.767–0.907), Poisson bounds (3.0 / 4.74 / 6.30),
per-frame budget (100 ms) — **sab sahi hain.**

**Lekin 31 jagah masle mile** — kuch chhote (naam/format), kuch aise jo implementation mein system ko
ghalat kar dete: SMS ka 30 s wait (target 20 s), clip hash wala signature (latency target se takraav),
manifest ko device key se sign karna (jab ke key site se bahar nahi jaati), aur sab se bada: **conformal
α ka matlab "per unit" hai, "per ghanta" nahi** — plan ke α = 0.01 se ~3–5 false alarms/camera-ghanta
bante (target 0.1). Neeche har masla, uska asar aur hal hai. Chalte hue system ko test karte waqt
**13 aur masle** mile (#32–44, table ke neeche; #39–44 asal video par) — wo bhi theek kar diye gaye.

## 2. Jo masle mile aur unka hal

| # | Section | Masla | Asar | Hal (v0.1 mein) |
|---|---|---|---|---|
| 1 | 8.8 vs US2, 7.11 | Sync loop SMS se pehle `age_s > 30` ka intezar karta hai | "Internet band → 20 s mein SMS" kabhi pura nahi hota | `sms_grace_s = 5`; online ho kar bhi undelivered high alert SMS jata hai. Test: `test_offline_high_alert_goes_by_sms_then_syncs` |
| 2 | 7.10 S1 vs 7.11 | Alert ke signature mein clip hash; clip ko +10 s post-roll chahiye | < 5 s alert latency aur clip hash ek saath mumkin nahi | Alert foran sign hota hai; clip ki alag **signed ClipAttestation** post-roll ke baad (ADR-0017) |
| 3 | 8.9 vs 7.12 | Manifest server par banta hai lekin "device private key" se sign hona tha | Device key ko server par lana padta = Restricted data ka ulanghan | **Do-layer signatures**: edge key (alerts, clips) + server evidence key (manifest) |
| 4 | US5, 8.9 | "1 byte badli file par ❌" — portal ke paas file hi nahi | Tamper test ka koi tareeqa nahi | Verify portal file ko **browser mein hash** karta hai (WebCrypto + HTTP LAN ke liye JS SHA-256) aur sirf hash bhejta hai; PDF ka hash server par |
| 5 | 8.6 vs 7.14, ADR-015 | "Har 2 s ka segment index" vs "activity-gated track-level" | 43k rows/camera/din vs ~3k | Track summaries (+ alert clips) index; 8.6 theek kiya |
| 6 | 11.1 vs 7.14 | Schema `vector(768)`, sizing `halfvec(768)` par | Storage ka hisaab 2x ghalat | `halfvec(768)` |
| 7 | 11.1 vs 7.11 | `alerts.status` = open/acked/resolved/false_alarm, state machine mein 8 states | Verifying/escalated/logged_only ka record nahi | `AlertStatus` = state machine |
| 8 | 7.14 vs 11.1 | "Har table mein tenant_id" lekin schema mein nahi | RLS/tenant isolation ka dawa khokhla | Har tenant table par `tenant_id`; site isolation tests (404) |
| 9 | 8.1 vs 11.4 | `AlertCandidate` mein severity, trace_id, schema_version nahi | Contract aur API example alag | Contract mein shamil + `supersedes` (upgrade) |
| 10 | 8.6 | Attributes hard filter bhi, `attr_match` score bhi | Score fusion bemaani | Sirf type hard; colour/riders/helmet soft score |
| 11 | 7.19 compose | `restart` policy nahi, healthchecks nahi, unpinned images, MinIO | Bijli ke baad stack khud nahi uthta (F4!); MinIO images Oct 2025 se band, repo Feb 2026 archived | `deploy/compose/*`: restart + healthcheck + pinned tags + local object store (ADR-0018) |
| 12 | 7.8 | RAM limits ka jod ~9.1 GB + OS ~3 GB > ~10 GB usable | Laptop par OOM | **Lite profile** (`make demo`, ~1 GB) roz ke liye (ADR-0016) |
| 13 | 8.8 | SMS jawab "1" — kai alerts khule hon to kis ka? | Ghalat alert ack | `1 A7F2` code support; ajnabi number ka jawab reject |
| 14 | 8.2 | T = 32 frames "10 fps par 3.2 s" — laptop 5 fps | Model ko alag device par alag tensor | Window seconds mein, 32 frames par resample |
| 15 | 8.19, US8 | Sirf YuNet face blur; CCTV par chehre 10–20 px | ≥ 98 % blur target mushkil | Har person ke **sir ka hissa** blur + YuNet (agar model ho) |
| 16 | 8.3 Tier 1 | "Re-ID se joda hua track" lekin re-ID Tier 2 mein | Tier 1 loitering re-entries gin hi nahi sakti | Foreground part-wise appearance re-ID baseline (bike body + riders' shirts), configurable threshold |
| 17 | **8.7, 14.7** | **α per unit hai; FA/camera-ghanta = α × units/ghanta** | Simulator: ~340 bike entities + ~520 bike–pedestrian pairs/ghanta → α=0.01 = ~3–5 FA/h | Candidate gating (≥ 2 chakkar; haath ka asal rabta) + `evaluate-fa` command (ADR-0021) |
| 18 | 8.7, 10.4 | Model update par calibration set purana | Ghalat p-values chupke se | Calibration file mein `model_version`; mismatch = uncalibrated warning |
| 19 | 8.9 | Merkle tree ka scheme likha nahi | Second-preimage risk | RFC 6962 (leaf/node prefixes) + inclusion proofs |
| 20 | 8.9 | "Canonical JSON" ki tareef nahi | Doosra verifier hash na mila sake | RFC 8785 (JCS) jaisa: sorted keys, ES6 numbers |
| 21 | 7.6 | Edge par Ultralytics = PyTorch (~1.5 GB) har device par | Bhaari image, RAM | Torch-free runtime: numpy YOLO decode (YOLO11 + YOLO26) + ByteTrack (ADR-0019) |
| 22 | 7.7, 10.1 | YOLO26 (NMS-free, Ultralytics ke mutabiq CPU par ~43 % tez) ka zikr nahi | Laptop FPS par asar | `models.yaml` mein `laptop-yolo26` profile; `make bench` muqabla |
| 23 | 7.4, 12 | Dashboard `next start` (Node server, 384 MB) | RAM | Static export, API hi serve karti hai; guard PWA usi app mein (ADR-0020, 0013) |
| 24 | 8.2, 9.3 | Pre-training NTU RGB+D par — research-only license | Release/commercial masla | **PakSnatch-sim**: simulator se license-free synthetic pose data (asal data phir bhi zaroori) |
| 25 | 7.4 | Workers alag process, WebSocket hub API mein — beech mein bus nahi | Escalation notifications dashboard tak nahi pahunchte | v0.1 workers in-process; Redis bus scale-out ke waqt (ADR-0007) |
| 26 | 8.6 | "kal" = guzra kal ya aane wala? | Search ghalat din | Search mein "kal" hamesha guzra kal (documented) |
| 27 | 8.17 | Escalation table ke columns ka matlab mubham | Timers ghalat | Cumulative timeline (0/60/120/300 s), timers DB mein (restart-safe) |
| 28 | 11.4 | IDs UUIDv7 — Python 3.12 mein nahi | — | RFC 9562 UUIDv7 implement |
| 29 | 8.9 | Hash-chained audit, concurrency ka zikr nahi | Do writers = toota chain | Single-writer lock (PG par advisory lock note) |
| 30 | 8.16 | Event mode ke calibration sets — fallback nahi | Naya mode = crash/uncalibrated | Mode set na ho to `normal` set |
| 31 | 14.5 | Demographic queries ("aurat", "larka") ka kya? | Privacy dawa toot sakta | Parser gender/umar filter mana karta hai aur note dikhata hai |

**Chalte system ki testing mein mile masle (v0.1):**

| # | Section | Masla | Asar | Hal |
|---|---|---|---|---|
| 32 | 8.17, F4 | Internet band ke dauran SMS se diya gaya ack sync hone par MTTA server ke "opened" waqt se gina gaya | Live demo mein MTTA **−18 s** | MTTA pehli insaani ittila (SMS ya app) se; ack event asal jawab ke waqt par. Test: `test_offline_sms_ack_keeps_real_times` |
| 33 | 14.7, F7 | `calibrate` / `evaluate-fa` dono cameras ko aik hi seed dete — aik hi scene do baar | FA do baar gina gaya, calibration ka `n` nakli taur par bara | Har (run, camera) ka alag seed; calibration dobara banaya |
| 34 | 8.2 | Snatch gate aik frame ki haath ki qurbat ko bhi "contact" maanta | Simulator ka wahid false alarm (drive-by, pedestrian ka koi jerk nahi) | Contact kam az kam 0.15 s (`min_close_s`); asal snatch scenarios (2.6 s) par asar nahi |
| 35 | 8.9, runbook | Server key rotate karne par purane evidence ki verification fail | Saal purana FIR evidence portal par "invalid" | `python -m jikimi_server retire-key` + `keys/retired/*.pub`; verify key-id se sahi key leta hai. Test: `test_evidence_stays_verifiable_after_server_key_rotation` |
| 36 | 8.11 | Rule builder "LLM structured output" par — ghalat zone/waqt bina dekhe camera par chalta | Khamosh false alarms ya khamosh surakh | Deterministic parser (sawal, guess nahi) + site validation + backtest + 2-person approval + pinned signed bundle (ADR-0022) |
| 37 | 8.16, 12.1 | Event mode mein bhi "kyun?" panel kehta "aam dinon mein X% se kam", aur mode edge tak pahunchne ka raasta hi nahi tha | Chand Raat ki alert ka matlab ghalat samjha jata; calendar sirf kaghaz par | Mode ka signed calendar edge tak; jumla us mode ka naam leta hai jis ke calibration set ne p-value di ("Chand Raat ko …"), set na ho to imaandari se "aam dinon" (ADR-0023) |
| 38 | 8.7, 8.16 | Plan tabdeeli pakadne ke liye KS drift par bharosa karta hai; naapne par KS festival rush ko **nahi** pakadta (har unit ka score wahi, sirf tadaad 2–5× aur loitering tail) | Admin mode confirm karna bhool jaye to rush wala din kisi ko nazar nahi aata | Edge heartbeat mein bike volume bamuqabla calibration units/ghanta; "normal" din ≥ 2× par dashboard mode confirm karne ko kehta hai (`eval/conformal_validity.py`) |
| 39 | 8.2, 8.3 | **Asal video:** ghane traffic mein rider association beech beech mein toot-ta; rider us frame mein "pedestrian" ban jata | Ek chaurahe ke 19 s clip mein 2 snatch false alarms | `RiderMemory`: jo shakhs apne ≥ 40 % frames mein rider tha, wo rider hi rehta hai |
| 40 | 8.2 | **Asal video:** bike ke bohat peeche khada shakhs image mein bike ko "chhoota" hai | Teesra false alarm | `same_depth`: victim aur bike ka scale ek hi faasle ka ho (unchai ka tanaasub 0.6–4) |
| 41 | 8.10 | Harkat karta camera (gaari / haath mein / hawa mein hilta pole): har cheez "tez" aur "jhatkay" wali lagti hai; "moved" check sirf reference se farq dekhta hai aur dhakke ke baad kabhi reset nahi hota | Snatch/loitering ke features be-maani | Har second ego-motion (ORB + RANSAC); "moving" status par snatch/loitering ALERT_NOW nahi |
| 42 | 8.19 | **Asal video:** blur sirf *detect* hue logon ka; bohat se riders kabhi person detect nahi hote | Chehre clip/snapshot mein reh jaate | Har two-wheeler ke upar riders ke sar ki pati bhi blur (`rider_head_proxy`); car ke peeche chhupe riders ab bhi baaqi |
| 43 | 7.8 | Pose model har us frame par jahan koi rider ho; FP32 YOLO laptop par | 455 ms/frame = 0.4 camera | Pose sirf jab pedestrian bike ki pahunch mein ho: 218–253 ms; zyada cameras ke liye INT8 OpenVINO |
| 44 | 8.2 | ST-GCN: training mein positive window = qareeb tareen rabte ke ±4 samples; plugin window bike ke jaane ke baad kaat-ta (jise training ne negative kaha) | Pipeline mein margin 0.508 vs 0.499 | Inference bhi rabte ke gird windows (`CONTACT_SPAN`, ek hi constant): 0.960 vs 0.836 |
| 45 | 8.10 | Camera jaan boojh kar ghumaya jaye to "moved" purane reference se kabhi match nahi karta | Camera hamesha "moved" alarm mein; asal tamper chhup jata | Admin ka "نیا منظر قبول کریں" (signed command, edge par ek hi baar) ya 10 min tak saakit rehne par khud naya reference + halka notice "zones dekh lein" (ADR-0026) |
| 46 | 8.1, F1 | **Asal video:** rang ka purana qaida har bike ko "black" kehta; sirf asal crops par tune kiya naya qaida simulator ki search gira deta (Recall@10 0.86 → 0.49: riders ke neeche neeli bikes gum) | "safed bike" search asal camera par bekaar | Qaida simulator + asal crops dono par chuna: chroma neeche ke band se, safed/silver/kaala riders ke upper body chhod kar, IR frame par koi rang nahi. Search 0.85 / MRR 1.00; asal crops 31 % → 66 % (white≈silver) |
| 47 | 8.12 | Voice reply ko seedha ack banana: Whisper "madad chahiye" ko "dekh liya" sun le to madad ki pukaar khamoshi se band | Guard ki jaan ka khatra | Server sirf likhta aur intent batata hai; guard tap kare tab hi bheja jata; help > ghalat > dekh liya; "nahi" ke saath jumla nahi ginta; audio save nahi; VAD (shor par khaali text) (ADR-0025) |
| 48 | 7.8 | INT8 export Ultralytics + PyTorch (CUDA build, GBs) aur COCO download maangta; FP32 se muqabla naapa hi nahi jata | Edge setup bhaari, INT8 ka asar andaza | NNCF + OpenVINO, local clip + simulator frames par calibration, FP32 se boxes/keypoints ka muqabla aur speed (ADR-0027): pipeline 1.7× tez; ek VERIFY snatch farq mila → pehle shadow mode |
| 49 | 8.20 | Wizard dashboard mein hota to RTSP password (DVR ka) server tak jata | Har site ke DVR ka password cloud par | Wizard edge par (`make setup-wizard`), PIN, password sirf `.env` mein (600), `site.yaml` comments ke saath, dono ka backup (ADR-0028) |
| 50 | 8.19 | OpenCV 5 mein Haar cascades nahi; `face_detector: haar` par crash | Blur config ki wajah se edge start na ho | Haar na ho to warning + head-region blur |
| 51 | 8.12 | faster-whisper 1.2.1 naye PyAV (19) par audio decode mein crash | Voice endpoint har baar fail | Apna chhota PyAV decoder (16 kHz mono, 15 s ki had) |
| 52 | 8.3 | Cross-camera route har naye segment par dobara score: prefix-wise calibration se normal routes par alert **2.8 %** at α = 1 % | Conformal guarantee toot jati | Route ka running maximum, aur calibration mein har normal route ek unit: 0.62 % (ADR-0029) |
| 53 | 8.3 | Trajectory model ka camera embedding sirf training wale cameras ke liye ma'ni rakhta hai | Doosri site par be-ma'ni scores | Model ke saath camera list; site ke cameras us mein na hon to cross-camera band |
| 54 | 8.4–8.5 | Laptop par chalne wala VLM (256M) snatch nahi pehchanta (AUC 0.40), chhote sample par "cover" 1.0 dikha jo 12 frames par 0.53 nikla | Ghalat "normal lagta hai" guard ko gumrah karta | VLM sirf un types par bole jo `vlm_check` mein AUC ≥ 0.8 pass karein (abhi koi nahi); advisory default (ADR-0030) |
| 55 | 8.21 | Bike embedding agar signed alert mein jaye to saal bhar evidence ke saath rehti (re-ID ki 24 h had toot-ti) | Privacy wada toot-ta | Embedding alag message, sirf opt-in site par, 24 h baad delete; share 2 h (ADR-0031) |
| 56 | 8.6 | Agent ka "kitni bikes" jawab sightings gin raha tha, aur "gate pe" ko narmi se le raha tha | Ghalat ginti | Sirf exact matches (rang, sawar, zone), distinct bikes |
| 57 | 8.18 | Zero-DCE++ andheray frame ko itna roshan karta ke noise kai guna: detector ne kam cheezein pakdin (0.56 → 0.25) | Raat mein detection aur kharab | Ablation ke baad enhancer default off; CLAHE ka faida bhi naye frames par 0 nikla |
| 58 | 8.15 | Hawkes simulation mein follow-ups ka branching ratio 1 se zyada (process phat jata) | Ghalat evaluation | α ki had (har zone par < 0.95 follow-up), fit grid bhi isi had mein |
| 59 | 8.12 | Bohat se Android phones mein Urdu TTS awaaz nahi; Urdu script ko Hindi awaaz nahi padhti | Guard alert sun nahi pata | Roman Urdu → Devanagari (`explanation_hi`), Hindi awaaz se Urdu sunai deti hai (ADR-0033) |
| 60 | 8.20 | Laptop / USB webcam source nahi tha | Live demo ke liye asli camera chahiye tha | `webcam:0` source (edge + wizard), 720p |
| 61 | 8.2 | Sirf bike snatching pakdi jati thi; paidal mobile chheenna, peecha, gherao, haathapai, zabardasti gaari mein daalna, girna, khari bike ki chori, bhagdar nahi | Guard ko hamle se **pehle** ka ishara nahi milta | F23: 4 naye plugins, sirf harkat (jins/umar/pehchaan kabhi nahi), har pattern ki apni calibration (ADR-0034) |
| 62 | 8.2 | Bachon ka "tag" khel haathapai lagta tha (score 0.90 → ALERT_NOW) | Jhoote "khatra" alert | Haathapai = jism jure rahein **aur** raftaar baar baar ulte (velocity reversals); bachon ka khel 0.27 |
| 63 | 8.2 | Dosto ka ghera / grahakon mein khara dukandar "gherao" lagta tha (0.9) | Bazaar mein roz jhoote alert | 3+ log, 4 s ke andar, kam az kam 120° alag simton se; jo pehle se khare the woh "gherne wale" nahi |
| 64 | 8.2 | Khari bike par jhuka shakhs rider-association mein "sawar" gina jata; chori ka waqt naapa hi nahi jata tha | Bike chori kabhi nahi pakdi jati | Chori plugin har shakhs ko dekhta hai (khari bike ka koi sawar nahi hota) |
| 65 | 8.2 | Bhagdar mein har qareeb jodi "paidal snatch" ban jati (4 alert) | Ek waqiye par kai ghalat alert | Usi waqt 2+ aur log bhaagein to snatch nahi, `crowd_panic` |
| 66 | 8.4 | `make calibrate` naye plugins ko aam traffic par calibrate kar ke street-life wali calibration mita deta | Har alert ALERT_NOW (normal mein koi milta-julta waqiya hi nahi) | Har plugin apni aam aabadi par: loitering/snatch → normal_traffic, safety → street_life |

## 3. Kya bana (v0.1) — Feature status

✅ = bana aur test hua · 🟡 = hissa bana / simulator par · ⏳ = roadmap (data, hardware ya Tier 2/3)

| ID | Feature | Status | Kahan / saboot |
|---|---|---|---|
| F1 | Roman Urdu search | ✅ search · ✅ agent (deterministic, read-only, har dawe ka clip hawala) | lexicon (365 variants) + time resolver + fuzzy; agent 48/48 scripted tasks; Analyst "تفتیش" chat; ADR-0032 |
| F2 | Bike loitering | ✅ Tier 1 (per-camera) · ✅ cross-camera routes (synthetic training) | normal routes 0.62 % FA at α 1 %, scouts 85 % by 3rd segment; site ka apna data pilot mein; ADR-0029 |
| F3 | Snatch detection | ✅ heuristic B1 · 🟡 ST-GCN (sirf synthetic data) | test AUC 0.978 [0.966, 0.989]; pipeline mein B1 ke saath shadow muqabla; asal video par 0 false alarms (fixes ke baad) |
| F4 | Offline-first | ✅ | outbox (kill -9 test), SMS (fake modem + AT modem), acks sync |
| F5 | Cascade + Urdu wajah | ✅ routing + templates · ✅ VLM verifier path (advisory/gate) · ⏳ qabil VLM | SmolVLM-256M kisi type par pass nahi (snatch AUC 0.40), isliye khamosh; ADR-0030 |
| F6 | VLM distillation | ✅ loop (sampling, 2/3 agreement, gate) · ⏳ qabil teacher | 256M teacher: 48/48 "unclear"; control round sahi labels ke saath: results.md |
| F7 | Conformal alerts | ✅ | per site/type/mode, version-bound, drift (KS), `evaluate-fa` |
| F8 | Evidence pack | ✅ | two-layer signatures, Urdu/English PDF + QR, Merkle, OTS hook, public verify |
| F9 | Benchmarks | 🟡 | datasheets, guides, consent forms, RUVR lexicon, PakSnatch-sim generator |
| F10 | Camera health / tamper | ✅ | covered, blur, moved (ORB), frozen, offline, moving (ego-motion); naya rukh qabool: admin button (signed command) ya 10 min baad khud (ADR-0026) |
| F11 | Rule builder | ✅ | Roman Urdu → DSL parser (16 server + 4 edge tests), site validation, 7-din backtest, approval, signed bundle + edge par key pin, dashboard "قواعد" page |
| F12 | Urdu voice | ✅ voice reply (Whisper small int8 → Urdu/Roman/Hindi intent, guard ki tasdeeq par hi bheja) · ✅ alert sunana (Urdu awaaz na ho to Hindi awaaz, Devanagari) · ⏳ 200 guard recordings | likhe 102 jawab: pehli baar 93.1 %; ADR-0025, ADR-0033 |
| F13 | Audio fusion | ✅ pipeline (log-mel → CNN → noisy-OR with flash / crowd-run), firecracker hard negative · ⏳ recordings | `train_audio --data`; synthetic sirf plumbing |
| F14 | Federated learning | ✅ FedAvg (3 virtual sites, DP noise option) | FedAvg AUC 0.944 vs sab data ek jagah 0.954 vs har site akeli 0.88–0.91; 3 sites par DP: σ 0.01 → ε ≈ 54,000 (asal privacy nahi), σ ≥ 0.1 → model khatam; asal DP ke liye saikron sites (results.md) |
| F15 | Hotspot + patrol | ✅ Hawkes + greedy patrol, dashboard "خطرے کا اندازہ" card | chhoti site par top-2 zones 0.54 (history 0.42); "risk estimate", prediction nahi |
| F18 | Low-light | ✅ bana + ablation · off by default | Zero-DCE++ nuqsaan (0.56 → 0.25), CLAHE neutral |
| F21 | Mohalla network | ✅ opt-in, sirf tasdeeq-shuda, embedding (tasveer nahi), 2 h, audit | server + edge tests; ADR-0031 |
| F16 | Event mode | ✅ | Hijri andaze (dependency ke baghair, 2024-25 Pakistani tareekhon se ±1 din), admin tasdeeq, signed calendar edge tak, din ka mode, mode-wise calibration + "kyun?" jumla, dashboard card (ADR-0023) |
| F17 | Escalation | ✅ | DB timers, guard → supervisor → owner, MTTA |
| F19 | Privacy by design | ✅ | head/face blur, encrypted originals, RBAC, retention job, FR blocklist |
| F20 | DVR onboarding | ✅ ONVIF WS-Discovery + stream URIs (WS-Security digest), Hikvision/Dahua/CP Plus/Uniview/TP-Link RTSP templates, stream test, **Urdu setup wizard edge par** (dhoondo → preview → zone → test → save) · ⏳ asal recorder par "< 10 min" | `make setup-wizard`, `discover` / `probe-stream`, 16 tests; ADR-0028 |
| F22 | SOS | ✅ | hold-to-send, offline queue, escalation |
| F23 | Zaati hifazat (naya) | ✅ paidal mobile snatch · ✅ hamle se pehle: peecha, gherao, haathapai, ghaseetna, zabardasti gaari mein, girna · ✅ khari bike chori · ✅ bhagdar · ⏳ asal footage | sirf harkat, jins/umar nahi; simulator golden + street-life FA (results.md "Personal safety"); ADR-0034 |

## 4. Naape gaye nateeje (simulator par — asal numbers abhi baaqi)

`docs/results.md` mein poori table hai. Ahem baatein:
- Golden replay: 18 runs (8 hard negatives), sab pass — `make replay`.
- Snatch: din aur raat dono scenarios mein ~3.4 s mein ALERT_NOW; delivery aur raasta poochhne par
  koi alert nahi.
- Loitering: pehle chakkar ke ~45 s baad (doosre chakkar par) ALERT_NOW — "waardaat se pehle".
- Edge → server latency ~1 s; internet band → SMS 5.0 s mein (live demo), guard ka SMS jawab internet aate hi ack ban kar sync.
- Roman Urdu search ~15 ms (lexicon path).
- Empirical false alarms (held-out simulated normal traffic): `docs/results.md`.

- False alarms: held-out simulated normal traffic ke **30 camera-ghante mein 0** (95 % bound 0.0999 < 0.1/ghanta).
- Asal video (ek ghane chaurahe ka free clip): pehle 3 snatch false alarms, unki wajah dhoondh kar theek kiye (#39–44) → 0; rang: 11 bikes mein ~7 saaf sahi, 3 do-rangi, 1 ghalat (pehle sab "black").
- Laptop par FP32 ONNX ~0.9 camera, **INT8 OpenVINO 1.3 camera** at 5 fps (150 ms/frame); INT8 ne clip par ek VERIFY snatch diya jo FP32 ne nahi → shadow mode zaroori.
- Voice reply: likhe 102 jawab par 93.1 % (pehli baar), shor/khamoshi par koi intent nahi; laptop par ~5 s fi jawab. Urdu recordings abhi nahi.
- Tier 2/3 (v2.4, zyadatar synthetic): cross-camera scouts 85 % 3rd segment tak (normal routes 0.62 % FA at α 1 %); agent 48/48 scripted tasks;
  hotspots chhoti site par top-2 zones 0.54 (history 0.42); VLM (256M) kisi kaam ka nahi nikla aur khamosh rehta hai; Zero-DCE++ ne detection kharab ki,
  isliye low-light off; audio aur federated ke liye `docs/results.md`.

**Imaandari:** ye sab simulator ke numbers hain, sirf ek asal clip ke siwa. Asal cameras, asal log aur asal raat ka data
(PakSnatch shoots, pilot) ke baghair koi accuracy dawa nahi kiya ja sakta (plan Section 14.6).

## 5. Kya abhi aap ke karne ka kaam hai (software se bahar)

1. **Permissions** (Section 9.1): university, ethics, police intimation, pilot site — Week 0.
2. **Customer interviews** (Section 20): 10–15 log; assumptions register (20.1) update.
3. **Models:** `uv run --with ultralytics python scripts/download_models.py --profile laptop` phir `make bench`
   (YOLO11n vs YOLO26n — aap ke i5-6200U par asal FPS).
4. **PakRoads-mini + PakSnatch-mini** collection (Solo track hafta 3–4), phir Kaggle par training.
5. **Pilot:** `docs/runbooks/pilot_setup.md` — 48–72 h calibration, shadow mode, phir live.

## 6. Mazeed behtari ke mashware (aage)

- Repo ko GitHub par daalne ke baad CI badges, aur `docs/` ko MkDocs site banana (`make docs`).
- Web Push (VAPID) taake guard app band ho tab bhi alert aaye (abhi SMS ye kaam karta hai).
- F12: 200 guard recordings (`eval.voice_check --audio`) se asal Urdu WER / intent; alert sunane ke liye
  recorded Urdu templates (bohat se Android phones mein Urdu awaaz nahi).
- F20 wizard ko asal recorder aur ek naye maalik ke saath time karna (plan: < 10 min).
- F5/F6: server GPU par bada VLM (same folder, `vlm_check` pass kare to khud istemal hoga).
- F2 / F15: har site ke apne normal routes aur incidents se trajectory model, calibration aur Hawkes fit.
- F13: firing / cheekh / sheesha / patakhon ki licensed ya apni recordings (`data/audio/<class>/`).
- F21: padosi sites ke tehreeri muahide (software sirf record karta hai).
- INT8 ko har site ki apni footage par dobara calibrate karna; VERIFY snatch farq ko shadow mode mein dekhna.
- Multi-replica scale-out ke liye Redis Streams bus (ADR-0007).
- Pehli asal Chand Raat / Eid ke baad us mode ka calibration asal footage se (ADR-0023); tab tak
  wo din aam dinon se compare hote hain aur "kyun?" panel ye batata hai.
- Bike ka **rang** har pilot site ki footage par dobara check karna (raat ka IR frame koi rang nahi deta; haze mein safed = silver).
- "moved" ke baad naya view qabool karne ka raasta (admin button ya 10 min sthir rehne par khud, audit ke saath).
- Laptop profile: OpenVINO INT8 export (`make models`) aur `eval.footage_check` se raftaar dobara naapna.
- Pilot par `evaluate-fa` jaisa hisaab asal footage par: kam az kam 30 saaf camera-ghante, taake
  "< 0.1 FA/camera-ghanta" 95 % par sabit ho (rule of three).
