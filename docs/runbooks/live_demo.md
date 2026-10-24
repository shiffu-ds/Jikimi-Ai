# Runbook: live demo with the laptop's webcam

One simulated gate camera plus this laptop's own webcam, the full stack on one machine.

1. **Build once:** `make web` (dashboard), models in `models/` (INT8 detector + pose: `uv run python
   scripts/quantize_openvino.py`; Whisper for voice replies: models/README.md).
2. **Start:** `make live` - seeds the live site config (`edge/config/site.live.yaml`, adds the
   camera `cam-webcam-01` with the zone "in front of the laptop") and starts the API, dashboard
   and edge. Open http://localhost:8000 and log in (users and the demo password: `.env`).
3. **Try, in this order:**
   - *Live cameras:* the webcam tile shows a blurred snapshot every few seconds; walk in and out.
   - *Camera covered:* put a hand over the webcam for 10 s -> tamper ALERT_NOW on the dashboard
     and in the guard app (`/guard/` in a second window, press "آواز آن کریں" once).
   - *Your own rule:* Rules page -> "camera 3 par koi 1 minute se zyada ruke to batao" (camera 3
     is the laptop) -> understand, propose, approve as admin. Sit in front of the laptop for a
     minute -> rule alert.
   - *Voice reply:* in the guard app press "بول کر جواب دیں", say "haan dekh liya", confirm the
     understood answer (needs the browser on this laptop: the microphone works on localhost).
   - *Investigate:* Analyst -> تفتیش, "aaj camera 3 par kaun aaya?", then "pehla clip dikhao".
4. **Stop:** Ctrl+C. The webcam is released with the edge.

Nothing leaves the laptop: no camera image is sent anywhere but the local server, faces are
blurred in every stored picture, and the snapshots stay in `data/`.
