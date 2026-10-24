# ADR-0021: Choose alpha from the candidate rate; gate candidates

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-23
- **Feature / gap:** F7, G29

## Context
Conformal control is per unit: FA/camera-hour <= alpha x (normal candidate units per camera-hour). Simulator calibration found ~300 bike entities and ~500 bike-pedestrian pairs per camera-hour, so alpha = 0.01 alone allows ~3-5 FA/h against a 0.1 target.

## Decision
Gate candidates before calibration-based routing (loitering: >= 2 passes and score >= 0.45; snatch: real hand contact), keep alpha small, and measure the empirical rate with `python -m jikimi_edge evaluate-fa` on held-out normal traffic.

## Consequences
The guarantee and the operational target are now connected by a formula, and every site report includes the measured FA/camera-hour.
