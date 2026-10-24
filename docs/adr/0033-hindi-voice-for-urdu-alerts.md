# ADR-0033: Phones without an Urdu voice read the alert with their Hindi voice

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-25
- **Feature / gap:** F12 (G03), plan risk "Urdu TTS quality"

## Context
The guard app reads alerts aloud with the phone's own text-to-speech. Many Android phones have a
Hindi voice but no Urdu one; given Urdu script, they read nothing useful. Spoken Urdu and Hindi
are one language, and the alerts' Roman Urdu text comes from fixed templates.

## Decision
The server adds `explanation_hi`: the Roman Urdu explanation in Devanagari (a dictionary for the
templates' words, nukta letters for Urdu sounds, spelling rules for names). The app speaks Urdu
with an Urdu voice when there is one, else the Devanagari text with a Hindi voice, else Urdu
script. A test renders every alert type and fails if any Latin letter is left for the voice to
spell.

## Consequences
The guard hears "Gate-1 par 23:41 baje ..." in a natural Hindustani voice on most phones, with
no model or recording to ship. Recorded Urdu templates remain the fallback the plan names for
phones with neither voice.
