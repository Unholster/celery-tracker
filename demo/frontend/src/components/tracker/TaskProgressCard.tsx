/**
 * TaskProgressCard - Collapsible section for displaying task progress.
 *
 * Shows task status, steps, subtask progress, errors, and duration.
 * Adapted from gna-benefits-recon's TaskProgressCard, replacing
 * @seisveinte/react and lucide-react with native elements and CSS.
 *
 * Features:
 * - Collapsible with chevron toggle
 * - Auto-expands when task starts
 * - Shows compact summary when collapsed
 * - Composes existing TaskTracker* components
 */

import { useCallback, useState } from "react";
import type { TrackedTaskDetail } from "./taskTracker";
import {
  cancelTrackedTask,
  isActiveStatus,
  type TrackedTaskStatus,
} from "./taskTracker";
import {
  TaskTrackerStatusBadge,
  TaskTrackerSubtasksProgress,
  TaskTrackerSubtasksList,
  TaskTrackerSteps,
  TaskTrackerProgressBar,
} from "./TaskTrackerProgress";

// =============================================================================
// Constants
// =============================================================================

const STATUS_COLORS: Record<string, string> = {
  pending: "#64748b",
  running: "#2563eb",
  completed: "#16a34a",
  failed: "#dc2626",
  cancelled: "#ea580c",
  partial_success: "#936C41",
  retrying: "#2563eb",
  stalled: "#d97706",
  queued: "#d97706",
};

const FALLBACK_COLOR = "#64748b";

// =============================================================================
// Types
// =============================================================================

export interface TaskProgressCardProps {
  /** The tracked task detail, or null if no task yet. */
  task: TrackedTaskDetail | null;

  /** Whether a task has been triggered but the TrackedTask hasn't been created yet. */
  isQueued?: boolean;

  /** Title displayed in the card header. Defaults to task name or type. */
  title?: string;

  /** Whether the card is collapsible. Defaults to true. */
  collapsible?: boolean;

  /** Whether the card starts expanded. Defaults to true. */
  defaultExpanded?: boolean;

  /** Compact mode: smaller padding, no card border. */
  compact?: boolean;

  /** Optional callback to render custom result content when task is completed. */
  renderResult?: (task: TrackedTaskDetail) => React.ReactNode;

  /**
   * Optional callback when the user dismisses a stale task warning.
   * Typically wired to useTaskControl's reset().
   */
  onDismissStale?: () => void;

  /**
   * Optional callback to re-run the task from the stale warning.
   * Shown as a "Re-run" button alongside Dismiss and Cancel.
   */
  onRetry?: () => void;
}

// =============================================================================
// Helper Functions
// =============================================================================

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

// =============================================================================
// Component
// =============================================================================

export function TaskProgressCard({
  task,
  isQueued = false,
  title,
  collapsible = true,
  defaultExpanded = true,
  compact = false,
  renderResult,
  onDismissStale,
  onRetry,
}: TaskProgressCardProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [isCancelling, setIsCancelling] = useState(false);
  const [staleDismissed, setStaleDismissed] = useState(false);

  const taskId = task?.id ?? null;

  const handleDismissStale = useCallback(() => {
    setStaleDismissed(true);
    onDismissStale?.();
  }, [onDismissStale]);

  const handleCancelTask = useCallback(async () => {
    if (!taskId) return;
    setIsCancelling(true);
    try {
      await cancelTrackedTask(taskId);
    } catch (err) {
      console.error("Failed to cancel task:", err);
    } finally {
      setIsCancelling(false);
    }
  }, [taskId]);

  const taskStatus = (task?.status ??
    (isQueued ? "pending" : null)) as TrackedTaskStatus | null;

  // ── Queued state (no TrackedTask yet) ──────────────────────────────
  if (isQueued && !task) {
    return (
      <CardWrapper compact={compact}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span className="tt-spinner" />
          <span style={{ fontSize: "0.875rem", fontWeight: 500 }}>
            {title ?? "Task Queued"}
          </span>
        </div>
        <p
          style={{
            margin: "8px 0 0",
            fontSize: "0.75rem",
            color: "#64748b",
          }}
        >
          The task has been queued and will start shortly…
        </p>
      </CardWrapper>
    );
  }

  // ── No task at all ─────────────────────────────────────────────────
  if (!task || !taskStatus) return null;

  const displayTitle =
    title ?? task.name ?? task.tracked_task_type ?? "Task Progress";

  const hasSteps = task.steps.length > 0;
  const subtasksTotal = task.subtasks_total;
  const subtasksCompleted = task.subtasks_completed;
  const subtasksFailed = task.subtasks_failed;
  const hasSubtasks = subtasksTotal > 0;
  const hasProgress = task.progress_total > 0;
  const isCompleted = task.status === "completed";
  const isFailed = task.status === "failed";
  const isPartialSuccess = task.status === "partial_success";
  const isStale = task.is_stale && !staleDismissed;
  const isActive = isActiveStatus(taskStatus);

  const toggleExpanded = () => {
    if (collapsible) setIsExpanded((prev) => !prev);
  };

  // Collapsed summary text
  const collapsedSummary = isCompleted
    ? "Completed"
    : isFailed
      ? "Failed"
      : isPartialSuccess
        ? "Completed with errors"
        : hasProgress
          ? `${task.progress_current} / ${task.progress_total}`
          : isActive
            ? "In progress…"
            : task.status;

  // Completion text
  const completionText =
    isCompleted || isPartialSuccess || isFailed
      ? `Finished in ${formatDuration(task.duration_seconds)}`
      : null;

  const color = STATUS_COLORS[task.status] ?? FALLBACK_COLOR;

  return (
    <CardWrapper compact={compact}>
      {/* ── Header ────────────────────────────────────────────────── */}
      <div
        onClick={toggleExpanded}
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          cursor: collapsible ? "pointer" : "default",
          userSelect: "none",
          padding: compact ? "0" : "0 0 4px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {/* Chevron (collapsible only) */}
          {collapsible && (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                transition: "transform 0.15s ease",
                transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)",
                fontSize: "0.875rem",
                color: "#64748b",
              }}
            >
              ▸
            </span>
          )}

          {/* Title */}
          <span style={{ fontSize: "0.875rem", fontWeight: 500 }}>
            {displayTitle}
          </span>

          {/* Status badge */}
          <TaskTrackerStatusBadge status={task.status} size="1" />
        </div>

        {/* Collapsed summary */}
        {!isExpanded && (
          <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
            {collapsedSummary}
          </span>
        )}
      </div>

      {/* ── Expanded content ──────────────────────────────────────── */}
      {isExpanded && (
        <div style={{ marginTop: "8px" }}>
          {/* Stale warning */}
          {isStale && (
            <div
              style={{
                padding: "8px 12px",
                borderRadius: "6px",
                backgroundColor: "#fffbeb",
                border: "1px solid #fde68a",
                marginBottom: "8px",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "8px",
                }}
              >
                <span
                  style={{ color: "#d97706", flexShrink: 0, marginTop: "1px" }}
                >
                  ⚠
                </span>
                <div style={{ flex: 1 }}>
                  <span
                    style={{
                      fontSize: "0.8125rem",
                      fontWeight: 500,
                      color: "#92400e",
                    }}
                  >
                    Task appears stale
                  </span>
                  <p
                    style={{
                      margin: "2px 0 0",
                      fontSize: "0.75rem",
                      color: "#a16207",
                    }}
                  >
                    This task hasn't sent updates in a while. The worker may
                    have crashed or been restarted.
                  </p>
                  <div
                    style={{
                      display: "flex",
                      gap: "6px",
                      marginTop: "8px",
                    }}
                  >
                    {onRetry && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRetry();
                        }}
                        style={{
                          ...smallButtonStyle,
                          backgroundColor: "#2563eb",
                          color: "#fff",
                          border: "1px solid #2563eb",
                        }}
                      >
                        ↻ Re-run
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDismissStale();
                      }}
                      style={smallButtonStyle}
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCancelTask();
                      }}
                      disabled={isCancelling}
                      style={{
                        ...smallButtonStyle,
                        color: "#dc2626",
                        borderColor: "#fca5a5",
                      }}
                    >
                      {isCancelling ? "Cancelling…" : "✕ Cancel"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Progress bar */}
          {hasProgress && (
            <div style={{ marginBottom: "8px" }}>
              <TaskTrackerProgressBar
                current={task.progress_current}
                total={task.progress_total}
                message={task.progress_message || undefined}
                color={color}
              />
            </div>
          )}

          {/* Subtasks progress */}
          {hasSubtasks && (
            <div style={{ marginBottom: "8px" }}>
              <TaskTrackerSubtasksProgress
                total={subtasksTotal}
                completed={subtasksCompleted}
                failed={subtasksFailed}
              />
            </div>
          )}

          {/* Per-subtask execution states (step-covered members already filtered by API) */}
          {task.tasks && Object.keys(task.tasks).length > 0 && (
            <div style={{ marginBottom: "8px" }}>
              <TaskTrackerSubtasksList tasks={task.tasks} compact={compact} />
            </div>
          )}

          {/* Steps */}
          {hasSteps && (
            <div
              style={{
                marginTop: "8px",
                paddingTop: hasProgress || hasSubtasks ? "8px" : "0",
                borderTop:
                  hasProgress || hasSubtasks ? "1px solid #e2e8f0" : "none",
              }}
            >
              <TaskTrackerSteps steps={task.steps} compact={compact} />
            </div>
          )}

          {/* Completion text */}
          {completionText && (
            <p
              style={{
                margin: "8px 0 0",
                fontSize: "0.75rem",
                color: "#64748b",
              }}
            >
              {completionText}
            </p>
          )}

          {/* Error message */}
          {isFailed && task.error_message && (
            <div
              style={{
                marginTop: "8px",
                padding: "8px",
                backgroundColor: "#fef2f2",
                borderRadius: "4px",
                fontSize: "0.75rem",
                color: "#dc2626",
                wordBreak: "break-word",
              }}
            >
              {task.error_message}
            </div>
          )}

          {/* Partial success message */}
          {isPartialSuccess && task.error_message && (
            <div
              style={{
                marginTop: "8px",
                padding: "8px",
                backgroundColor: "#fffbeb",
                borderRadius: "4px",
                fontSize: "0.75rem",
                color: "#92400e",
                wordBreak: "break-word",
              }}
            >
              {task.error_message}
            </div>
          )}

          {/* Custom result renderer */}
          {renderResult &&
            (isCompleted || isPartialSuccess) &&
            renderResult(task)}

          {/* Cancel button (for active tasks, no stale warning shown) */}
          {isActive && !isStale && (
            <div
              style={{
                marginTop: "8px",
                display: "flex",
                justifyContent: "flex-end",
              }}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCancelTask();
                }}
                disabled={isCancelling}
                style={{
                  ...smallButtonStyle,
                  color: "#dc2626",
                  borderColor: "#fca5a5",
                }}
              >
                {isCancelling ? "Cancelling…" : "✕ Cancel"}
              </button>
            </div>
          )}
        </div>
      )}
    </CardWrapper>
  );
}

// =============================================================================
// Sub-components
// =============================================================================

function CardWrapper({
  compact,
  children,
}: {
  compact?: boolean;
  children: React.ReactNode;
}) {
  if (compact) {
    return <div>{children}</div>;
  }

  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid #e2e8f0",
        borderRadius: "8px",
        backgroundColor: "#fafafa",
      }}
    >
      {children}
    </div>
  );
}

// =============================================================================
// Shared inline styles
// =============================================================================

const smallButtonStyle: React.CSSProperties = {
  padding: "4px 10px",
  fontSize: "0.75rem",
  fontWeight: 500,
  fontFamily: "inherit",
  borderRadius: "4px",
  border: "1px solid #d1d5db",
  backgroundColor: "transparent",
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  gap: "4px",
  lineHeight: 1.4,
};
