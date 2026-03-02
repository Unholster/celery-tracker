"""Level 4 — Fan-out with parallel sections (group + chain).

The most detailed variant: the report-generation process fans out the
analysis phase into three parallel sections — **Revenue**, **Customers**,
and **Inventory** — then gathers the results and finishes with compile
and deliver.

The canvas structure is::

    fetch_data  →  group(analyze_revenue,  →  compile_report  →  deliver
                         analyze_customers,
                         analyze_inventory)

Dispatched with::

    with tracker.track("Report — fan-out") as t:
        generate_report_fanout_canvas().apply_async()

The ``track()`` context manager stamps the first published task.
Celery propagates the stamp through the chord and chain callbacks,
and the global ``before_task_publish`` signal handler registers each
task as a member of the tracker as it is dispatched.  The three
parallel analysis sections all register at once (published client-side
as a group), while the chord callback and final delivery step register
on the worker side as they are triggered.

Each task is also decorated with ``@tracker.step("…")`` so the phase
appears in *both* ``tasks`` (from signal-based member registration)
and ``steps`` (as it executes, with timing).

From the UI's perspective the user sees task-level progress with
the parallel analysis sections running simultaneously, and the final
steps completing in sequence.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from celery import chain, chord, group

import tracker

from . import app
from ._report import PHASES, simulate

logger = logging.getLogger(__name__)


# =============================================================================
# Canvas builder
# =============================================================================

# Reuse timing from the shared PHASES for fetch / compile / deliver.
_FETCH = PHASES[0]
_COMPILE = PHASES[3]
_DELIVER = PHASES[4]

# The three parallel analysis sections share the "Analyze" phase timing
# but each focuses on a different domain.
_ANALYSIS_SECTIONS: list[tuple[str, float, float]] = [
    ("Analyze revenue", 1.5, 4.0),
    ("Analyze customers", 2.0, 5.0),
    ("Analyze inventory", 1.0, 3.0),
]


def generate_report_fanout_canvas():
    """Build the 'Report (fan-out)' canvas.

    Structure: fetch → chord([revenue, customers, inventory], compile) → deliver
    """
    return chain(
        fetch_data_fo.s(),
        chord(
            group(
                analyze_revenue.s(),
                analyze_customers.s(),
                analyze_inventory.s(),
            ),
            compile_report_fo.s(),
        ),
        deliver_fo.s(),
    )


CANVAS_RECIPES: dict[str, tuple[str, Callable]] = {
    "report_fanout": ("Report — fan-out", generate_report_fanout_canvas),
}


# =============================================================================
# Tasks — each is a Celery task *and* a tracked step
# =============================================================================


@app.task
@tracker.step(_FETCH[0])
def fetch_data_fo():
    """Pull rows from the sales database."""
    return simulate(*_FETCH)


@app.task
@tracker.step(_ANALYSIS_SECTIONS[0][0])
def analyze_revenue(prev: dict):
    """Compute revenue metrics and trends."""
    return simulate(*_ANALYSIS_SECTIONS[0])


@app.task
@tracker.step(_ANALYSIS_SECTIONS[1][0])
def analyze_customers(prev: dict):
    """Analyze customer acquisition and churn."""
    return simulate(*_ANALYSIS_SECTIONS[1])


@app.task
@tracker.step(_ANALYSIS_SECTIONS[2][0])
def analyze_inventory(prev: dict):
    """Assess inventory levels and turnover."""
    return simulate(*_ANALYSIS_SECTIONS[2])


@app.task
@tracker.step(_COMPILE[0])
def compile_report_fo(section_results: list):
    """Assemble the final PDF / HTML from all analysis sections."""
    result = simulate(*_COMPILE)
    result["sections"] = len(section_results) if section_results else 0
    return result


@app.task
@tracker.step(_DELIVER[0])
def deliver_fo(prev: dict):
    """Email the report and upload to S3."""
    result = simulate(*_DELIVER)
    msg = f"Report delivered ({result['seconds']:.1f}s for final stage)"
    logger.info(msg)
    return msg
