# PakRoads - datasheet (draft)

Template from "Datasheets for Datasets" (Gebru et al.). Fill every section before release.

| | |
|---|---|
| Version | pakroads-v0 (not collected yet) |
| Task | object detection, 14 classes (`classes.yaml`) |
| Target size | 6,000-8,000 images, >= 3 cities, >= 40 videos |
| Splits | video/location-disjoint 70/15/15 (`splits/*.txt`, fixed) |
| License | CC BY-NC 4.0 (see `DATA_LICENSE.md`) |

## Motivation
Pakistani roads have classes COCO lacks (qingqi, loader rickshaw, donkey cart) and pillion/helmet
attributes that matter for street safety. Bangladesh has Dhaka-AI; Pakistan had no public set.

## Composition
Frames from CCTV height (3-5 m) and dash cameras; day, dusk, night, dust, rain/smog. Faces blurred
before release. No identity labels.

## Collection process
Permissioned locations only; owner/management consent for private premises; city footage only
where filming is legal. Pre-labelling with an open-vocabulary detector, then human correction in CVAT.

## Quality
10 % double-labelled; report Cohen's kappa (class) and mean box IoU agreement; disagreements
resolved in a weekly meeting; the guide's edge cases (`annotation_guide.md`) are updated after each.

## Uses / not-for uses
For: detection research, benchmarking, edge model training. **Not for:** identifying people,
face recognition, demographic analysis, enforcement without human review.

## Maintenance
Issues via the `dataset_issue` template; withdrawn images removed in the next version.
