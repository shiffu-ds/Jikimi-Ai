#!/usr/bin/env bash
# Recorded videos -> RTSP "cameras" on MediaMTX (development without hardware, plan Section 7.8).
# deploy/fake-cams/videos.txt: one "<camera_id> <path/to/video.mp4>" per line (H.264, no re-encode).
set -euo pipefail
LIST="${1:-deploy/fake-cams/videos.txt}"
[ -f "$LIST" ] || { echo "missing $LIST (copy videos.txt.example)"; exit 1; }
while read -r cam video; do
  [ -z "${cam:-}" ] || [ "${cam:0:1}" = "#" ] && continue
  echo "publishing $video as rtsp://localhost:8554/$cam"
  ffmpeg -nostdin -loglevel error -re -stream_loop -1 -i "$video" -c:v copy -an \
         -f rtsp -rtsp_transport tcp "rtsp://localhost:8554/${cam}" &
done < "$LIST"
wait
