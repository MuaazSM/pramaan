"""Dramatiq jobs: imaging, scans, parsing, analytics.

Wave 0 (W0.3) ships only the job-runner *interface* (``runner.py``) so
``apps/api`` can type its job responses against something real; the actual
pipeline stages (hash_verify, fingerprint, parse_index, ...) are a later
BACKEND task. See ``docs/progress/W0.3.md``.
"""

__version__ = "0.1.0"
