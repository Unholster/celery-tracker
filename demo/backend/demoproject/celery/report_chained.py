"""Level 3 — Chain of individual Celery tasks.

Each phase of the report-generation process is its own ``@app.task``,
and the full pipeline is built as a Celery **chain**.

Dispatched with::

    with tracker.track("Report — chained") as t:
        generate_report_chained_canvas().apply_async()

The ``track()`` context manager stamps the first task in the chain.
Celery propagates the stamp to each subsequent callback, and the
global ``before_task_publish`` signal handler registers each task as
a member of the tracker as it is dispatched by the worker.  Members
appear incrementally — one per chain link — rather than all at once.

Each task is also decorated with ``@tracker.step("…")`` so the phase
appears in *both* ``tasks`` (from signal-based member registration)
and ``steps`` (as it executes, with timing).

From the UI's perspective the user sees tasks appearing one-by-one as
the chain progresses, transitioning from ``running`` → ``completed``.
The steps list fills in alongside with per-phase durations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from celery import chain

import tracker

from . import app
from ._report import PHASES, simulate

logger = logging.getLogger(__name__)


# =============================================================================
# Canvas builder
# =============================================================================


def generate_report_chained_canvas():
    """Build the 'Report (chained)' canvas: a five-stage chain."""
    return chain(
        fetch_data.s(),
        analyze.s(),
        generate_charts.s(),
        compile_report.s(),
        deliver.s(),
    )


CANVAS_RECIPES: dict[str, tuple[str, Callable]] = {
    "report_chained": ("Report — chained", generate_report_chained_canvas),
}


# =============================================================================
# Pipeline stages — each is a Celery task *and* a tracked step
# =============================================================================

# Unpack phase definitions so each task uses consistent timing.
_FETCH = PHASES[0]
_ANALYZE = PHASES[1]
_CHARTS = PHASES[2]
_COMPILE = PHASES[3]
_DELIVER = PHASES[4]


@app.task
@tracker.step(_FETCH[0])
def fetch_data():
    """Pull rows from the sales database."""
    return simulate(*_FETCH)


@app.task
@tracker.step(_ANALYZE[0])
def analyze(prev: dict):
    """Compute revenue metrics and trends."""
    return simulate(*_ANALYZE)


@app.task
@tracker.step(_CHARTS[0])
def generate_charts(prev: dict):
    """Render visualisations."""
    return simulate(*_CHARTS)


@app.task
@tracker.step(_COMPILE[0])
def compile_report(prev: dict):
    """Assemble the final PDF / HTML."""
    return simulate(*_COMPILE)


@app.task
@tracker.step(_DELIVER[0])
def deliver(prev: dict):
    """Email the report and upload to S3."""
    result = simulate(*_DELIVER)
    total_secs = result["seconds"]
    msg = f"Report delivered ({total_secs:.1f}s for final stage)"
    logger.info(msg)
    return msg
