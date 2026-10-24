# ADR-0009: Self-hosted models by default; remote providers opt-in

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** G28

## Context
Privacy, cost and offline operation.

## Decision
LLM/VLM calls go to an OpenAI-compatible local server (Ollama / llama.cpp / vLLM) only when configured.

## Consequences
Without an LLM, search stays lexicon-only (deterministic, fast); VERIFY alerts open as unverified.
