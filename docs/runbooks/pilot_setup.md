# Runbook: pilot site setup (plan Section 16.3)

1. **Agreement + signage** signed; Urdu/English "Is ilaqe mein AI CCTV hai" boards installed.
2. **Edge box** (laptop or Intel mini PC): Ubuntu/Kali, full-disk encryption (LUKS), `sudo apt install ffmpeg`,
   clone the repo, `make setup`, set `HandleLidSwitch=ignore` for laptops.
3. **Cameras (wizard):** copy `edge/config/site.example.yaml` to `edge/config/site.yaml` (delete its
   two example cameras), then `make setup-wizard EDGE_CFG=edge/config/site.yaml` and open the
   printed address on a phone on the same network; enter the PIN shown on the edge. Per camera:
   search (ONVIF) or pick the brand and type the recorder's IP, channel, user and password ->
   connection test (use the sub-stream if it says "heavier than 720p") -> tap the corners of the
   area to watch -> detector test -> save. The RTSP URL goes into `.env`, the camera and zone into
   `site.yaml` (backups `*.bak-<time>` next to them). On a shared Wi-Fi the password crosses the
   LAN unencrypted: use a cable, or run the wizard on the edge itself with `--host 127.0.0.1`.
   Stop it with Ctrl+C when done and restart the edge.
   **Cameras (command line):** `python -m jikimi_edge --config edge/config/site.yaml discover`
   (ONVIF; add `--user admin --password-env DVR_PASSWORD` to list each recorder's stream URIs); no
   ONVIF? `onboarding/templates.py` has the common brands' RTSP templates. Put the sub-stream URLs
   in `.env` (`CAM_GATE_01_RTSP=...`), test each with `probe-stream --url-env CAM_GATE_01_RTSP`, and
   write the zones (normalized polygons) into `site.yaml` by hand.
4. **Models:** `make models PROFILE=laptop` (exports YOLO to OpenVINO INT8; or, without PyTorch,
   `uv run python scripts/quantize_openvino.py` on the ONNX models, calibrated on local frames:
   put a few minutes of the site's own footage in `data/footage/` first), then `make bench`.
   Before going live, run the edge on a few minutes of the site's *own* recorded footage:
   `python -m eval.footage_check <clip>.mp4 --profile laptop` (detections, tracks, colours, alerts,
   camera health, ms per frame). Footage without incidents is a false-alarm check: every alert on
   it needs an explanation before the pilot starts.
5. **Keys:** `python -m jikimi_edge --config edge/config/site.yaml keygen` → register the public key on the
   server (`python -m jikimi_server seed --edge-config edge/config/site.yaml`) → token file is written to
   `data/edge/keys/device.token`.
6. **SMS:** plug the GSM modem (PTA-registered, organisation SIM), set `JIKIMI_SMS_GATEWAY=modem`,
   `GUARD_SMS_NUMBERS=...`, test with `python -m jikimi_edge sms-test --to +92...`.
7. **Calibration (48-72 h):** run in shadow mode (alerts logged, not notified), have guards confirm the
   footage is normal, then calibrate on it; check `evaluate-fa` style numbers before going live.
8. **Systemd:** install `deploy/provisioning/systemd/*.service`, enable, reboot test (power cut).
9. **Guard training (30 min, Urdu):** guard app, "1/2/3" SMS replies, SOS hold.
10. **Weekly review:** false alarms, missed events, MTTA; recalibrate if drift is flagged.
11. **Rules (F11):** let the supervisor write the site's own rules on the dashboard's Rules page
    (Roman Urdu), check the 7-day backtest, approve as admin, and confirm the "running on the edge"
    badge appears within ~2 minutes.
12. **Event modes (F16), before every Ramadan / Eid / Muharram / 14 August:** confirm the Hijri
    estimates on the Rules page once the moon is sighted (fix the date if needed) and add local
    bazaar days. After the first such event, calibrate its mode from 48-72 h of guard-confirmed
    footage of those days (as in step 7, writing e.g. the `chand_raat` set; the simulator version is
    `calibrate --scenario festival_traffic --mode chand_raat`); until then those days are compared
    with ordinary days, and the "kyun?" panel says so.
