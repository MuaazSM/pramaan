"""Deterministic demo-case fixtures (docs/PROMPTBOOK.md W0.3).

``generate.build()`` produces the whole in-memory dataset from fixed
constants and a seeded RNG only — no wall-clock reads, no unseeded
randomness — so re-running it byte-for-byte reproduces the same data
(CLAUDE.md rule 5). ``store`` wraps the built dataset in small read/query
helpers that every router imports instead of touching ``generate`` directly.
"""
