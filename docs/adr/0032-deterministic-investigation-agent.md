# ADR-0032: The investigation agent is deterministic, read-only and cites every claim

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-25
- **Feature / gap:** F1 Tier 2 (G01, G02, G04)

## Context
The plan's analyst agent answers multi-turn questions ("kal raat kaali bike 2 sawar ... ye bike
aur kahan gayi ... report banao") with tools, guardrails and clip citations. A tool-calling LLM
would need a server GPU or a cloud API; the product must also run on one laptop, and an agent
that invents a sighting is worse than none.

## Decision
A deterministic planner over the same lexicon parser as search: find, follow a bike across
cameras, show a clip, count, draft a report, list cameras. Tools only read; the report is a
draft and exporting stays a human's button. At most 8 tool calls per turn; every answer cites
clip ids of the user's site, and an answer without citations becomes "nothing found"; the
context the client sends back is re-checked against the user's sites; every turn is audited.
"The same bike" is said only for the same anonymous entity on one camera - on other cameras the
agent reports a *similar* bike (same colour and riders within 30 min), since the server holds no
appearance embeddings.

## Consequences
48 of 48 scripted tasks pass with one tool call each (the tasks are written for this agent:
they check plumbing and guardrails). Free-form questions outside its intents get "rephrase" with
examples; an LLM planner can be added behind the same tools and guardrails later.
