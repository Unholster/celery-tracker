"""Shared simulation helpers for the report-generation demos.

Every demo task models the same five-phase process — generating a
quarterly sales report — but each variant exposes a different level of
tracking detail.  This module holds the shared constants and the
``simulate`` helper so the actual work (random sleep + logging) is
identical across all four variants.

Phases
------
1. **Fetch data** — pull rows from the sales database
2. **Analyze** — compute revenue metrics and trends
3. **Generate charts** — render visualisations
4. **Compile report** — assemble the final PDF / HTML
5. **Deliver** — email the report and upload to S3
"""

from __future__ import annotations

import logging
import random
from time import sleep

logger = logging.getLogger(__name__)

# Phase definitions: (label, min_seconds, max_seconds)
PHASES: list[tuple[str, float, float]] = [
    ("Fetch data", 1.0, 3.0),
    ("Analyze", 1.5, 4.0),
    ("Generate charts", 1.0, 3.5),
    ("Compile report", 0.5, 2.0),
    ("Deliver", 0.5, 1.5),
]


def simulate(label: str, min_secs: float, max_secs: float) -> dict:
    """Simulate one phase of report generation.

    Sleeps for a random duration, logs what happened, and returns a small
    result dict that the next phase can consume.
    """
    secs = random.uniform(min_secs, max_secs)
    sleep(secs)
    rows = random.randint(50, 500)
    logger.info("%s — %d items in %.2fs", label, rows, secs)
    return {"phase": label, "items": rows, "seconds": round(secs, 2)}
