"""Level 1 — Single task, no tracking detail.

The simplest possible approach: one ``@app.task`` that runs all five
phases of the report-generation process sequentially inside a single
function body.  No steps, no progress — the tracker only knows that
the task is pending, running, or finished.

Dispatched with::

    with tracker.track("Report — basic") as t:
        generate_report_basic.delay()

From the UI's perspective this is an opaque black box: the user sees
*"Processing…"* and then *"Completed"* with no intermediate feedback.
"""

import logging

from . import app
from ._report import PHASES, simulate

logger = logging.getLogger(__name__)


@app.task
def generate_report_basic():
    """Generate a quarterly sales report (no tracking detail)."""
    results = [simulate(label, lo, hi) for label, lo, hi in PHASES]
    total_items = sum(r["items"] for r in results)
    total_secs = sum(r["seconds"] for r in results)
    msg = f"Report complete: {total_items} items processed in {total_secs:.1f}s"
    logger.info(msg)
    return msg
