# Runbook: model update and rollback

1. New model → golden replay (`make replay`) and test-set metrics must not regress (plan 10.3).
2. **Recalibrate** for the new scorer: calibration files record `model_version`; a mismatch makes the
   edge treat alerts as *uncalibrated* (raw-score thresholds) until `calibrate` is re-run.
3. Shadow mode for 7 days, compare with production alerts, then switch `plugins.snatch.model`.
4. Rollback = point the config back to the previous file (kept in `models/`) and restart the edge.
