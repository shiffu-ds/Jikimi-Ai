# PakSnatch - datasheet (draft)

| | |
|---|---|
| Version | paksnatch-v0 (staged shoots not started) + **paksnatch-sim** (synthetic, available) |
| Task | snatch / attempt / loitering / hard negatives / normal (clip level + temporal boundaries) |
| Target size | 400 snatch, 100 attempt, 150 loitering sequences, 600 hard negatives, >= 50 camera-hours normal |
| Splits | **actor- and location-disjoint** test set |
| License | CC BY-NC 4.0 |

## Synthetic pre-training set (PakSnatch-sim)
`python -m jikimi_ml.data.synthetic` renders randomised encounters (direction, speeds, lane,
meeting point, reach timing, which rider reaches, pedestrian jerk) plus hard negatives (delivery
hand-over, asking directions) and normal traffic from the edge simulator, and cuts exactly the
tensors the edge model consumes. It replaces research-only NTU RGB+D pre-training; it does **not**
replace real, consented fine-tuning data.

## Collection (real)
Staged by consenting adult actors (>= 20, mixed ages, both genders), dummy phones/bags, closed or
low-traffic road, safety officer present, written notice to campus security and the local police
station, "Filming in progress" banners (plan Section 9.1). See `scenarios.md`, `shot_list.csv`.

## Labels (`labels.jsonl`, plan Section 9.7)
`clip_id, video, cameras, label, start_frame, end_frame, fps, actors, conditions, split, consent_ids`.
Rows without `consent_ids` are rejected by the loader.

## Not-for uses
Identity tracking, face recognition, demographic inference.
