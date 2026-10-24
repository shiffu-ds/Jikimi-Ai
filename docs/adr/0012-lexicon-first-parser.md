# ADR-0012: Lexicon-first Roman Urdu parser, LLM fallback

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F1, G01

## Context
LLMs on a 2-core CPU are slow and non-deterministic; Roman Urdu spelling varies a lot.

## Decision
A spelling-variant lexicon + fuzzy matching + deterministic time resolver; the LLM is called only below 60 % coverage.

## Consequences
Parsing takes milliseconds and is testable (33 cases); the lexicon is published with RUVR.
