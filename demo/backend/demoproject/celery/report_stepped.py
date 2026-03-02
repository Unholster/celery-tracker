"""Level 2 — Single task with tracked steps.

Same single ``@app.task`` as Level 1, but each phase is wrapped in a
``with tracker.step("…"):`` context manager.  This tells the tracker
*what* the task is doing right now — each step appears in the ``steps``
list as it starts, and is marked completed (with timing) when it
finishes.

Dispatched with::

    with tracker.track("Report — stepped") as t:
        generate_report_stepped.delay()

From the UI's perspective the user sees a live checklist: each phase
lights up as "running" and then flips to "completed" with its duration.
However, steps only become visible when they *start* — the user cannot
see how many phases remain until the task reaches them.
"""

import logging

import tracker

from . import app
from ._report import PHASES, simulate

logger = logging.getLogger(__name__)


@app.task
def generate_report_stepped():
    """Generate a quarterly sales report (with tracked steps)."""
    results = []
    for label, lo, hi in PHASES:
        with tracker.step(label):
            results.append(simulate(label, lo, hi))

    total_items = sum(r["items"] for r in results)
    total_secs = sum(r["seconds"] for r in results)
    msg = f"Report complete: {total_items} items processed in {total_secs:.1f}s"
    logger.info(msg)
    return msg
