/**
 * Task Tracker Progress Components
 *
 * Plain-HTML/CSS components for displaying task progress, steps, and status.
 * Adapted from gna-benefits-recon's TaskTrackerProgress, replacing
 * @seisveinte/react and lucide-react with native elements and CSS.
 */

import type {
  TaskExecutionState,
  TrackedTaskDetail,
  TrackedTaskListItem,
  TrackedTaskStep,
} from "./taskTracker";

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

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Processing",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  partial_success: "Completed with Errors",
  retrying: "Retrying",
  stalled: "Stalled",
  queued: "Queued",
};

const STEP_STATUS_SYMBOLS: Record<string, string> = {
  pending: "○",
  running: "◎",
  completed: "✓",
  skipped: "⏭",
  failed: "✗",
};

const STEP_STATUS_COLORS: Record<string, string> = {
  pending: "#94a3b8",
  running: "#2563eb",
  completed: "#16a34a",
  skipped: "#94a3b8",
  failed: "#dc2626",
};

const FALLBACK_COLOR = "#64748b";
const FALLBACK_LABEL = "Unknown";

// =============================================================================
// Shared styles (injected once)
// =============================================================================

let stylesInjected = false;

function injectStyles() {
  if (stylesInjected) return;
  stylesInjected = true;

  const style = document.createElement("style");
  style.textContent = `
    @keyframes tt-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    @keyframes tt-indeterminate {
      0% { transform: translateX(-100%); }
      100% { transform: translateX(400%); }
    }
    .tt-spinner {
      display: inline-block;
      width: 10px;
      height: 10px;
      border: 2px solid currentColor;
      border-top-color: transparent;
      border-radius: 50%;
      animation: tt-spin 0.8s linear infinite;
      flex-shrink: 0;
    }
    .tt-spinner--sm {
      width: 8px;
      height: 8px;
      border-width: 1.5px;
    }
    .tt-spinner--lg {
      width: 14px;
      height: 14px;
      border-width: 2px;
    }
  `;
  document.head.appendChild(style);
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

function formatTime(timestamp: string | null): string {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// =============================================================================
// Spinner Component
// =============================================================================

function Spinner({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  injectStyles();
  const cls =
    size === "sm"
      ? "tt-spinner tt-spinner--sm"
      : size === "lg"
        ? "tt-spinner tt-spinner--lg"
        : "tt-spinner";
  return <span className={cls} />;
}

// =============================================================================
// TaskTrackerStatusBadge
// =============================================================================

interface TaskTrackerStatusBadgeProps {
  status: string;
  size?: "1" | "2";
}

export function TaskTrackerStatusBadge({
  status,
  size = "1",
}: TaskTrackerStatusBadgeProps) {
  injectStyles();

  const isActive =
    status === "running" || status === "retrying" || status === "queued";
  const color = STATUS_COLORS[status] ?? FALLBACK_COLOR;
  const label = STATUS_LABELS[status] ?? FALLBACK_LABEL;

  const fontSize = size === "1" ? "0.75rem" : "0.8125rem";
  const padding = "3px 8px";

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        padding,
        borderRadius: "9999px",
        backgroundColor: `${color}20`,
        color,
        fontSize,
        fontWeight: 500,
        lineHeight: 1.4,
        whiteSpace: "nowrap",
      }}
    >
      {isActive && <Spinner size="sm" />}
      {label}
    </span>
  );
}

// =============================================================================
// TaskTrackerProgressBar
// =============================================================================

interface TaskTrackerProgressBarProps {
  current: number;
  total: number;
  message?: string;
  showPercent?: boolean;
  height?: number;
  color?: string;
}

export function TaskTrackerProgressBar({
  current,
  total,
  message,
  showPercent = true,
  height = 8,
  color = "#2563eb",
}: TaskTrackerProgressBarProps) {
  injectStyles();

  const percent =
    total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
  const isIndeterminate = total === 0;

  return (
    <div style={{ width: "100%" }}>
      {/* Bar track */}
      <div
        style={{
          width: "100%",
          height: `${height}px`,
          backgroundColor: "#e2e8f0",
          borderRadius: `${height / 2}px`,
          overflow: "hidden",
        }}
      >
        {isIndeterminate ? (
          <div
            style={{
              width: "30%",
              height: "100%",
              backgroundColor: color,
              borderRadius: `${height / 2}px`,
              animation: "tt-indeterminate 1.5s infinite ease-in-out",
            }}
          />
        ) : (
          <div
            style={{
              width: `${percent}%`,
              height: "100%",
              backgroundColor: color,
              borderRadius: `${height / 2}px`,
              transition: "width 0.3s ease",
            }}
          />
        )}
      </div>

      {/* Label row */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: "4px",
        }}
      >
        <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
          {message ||
            (isIndeterminate ? "Processing..." : `${current} / ${total}`)}
        </span>
        {showPercent && !isIndeterminate && (
          <span
            style={{ fontSize: "0.75rem", color: "#64748b", fontWeight: 500 }}
          >
            {percent}%
          </span>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// TaskTrackerSubtasksProgress
// =============================================================================

interface TaskTrackerSubtasksProgressProps {
  total: number;
  completed: number;
  failed: number;
  showBar?: boolean;
}

export function TaskTrackerSubtasksProgress({
  total,
  completed,
  failed,
  showBar = true,
}: TaskTrackerSubtasksProgressProps) {
  if (total === 0) return null;

  const done = completed + failed;
  const percent = Math.min(100, Math.round((done / total) * 100));
  const successPercent = Math.min(100, Math.round((completed / total) * 100));
  const failedPercent = Math.min(
    100 - successPercent,
    Math.round((failed / total) * 100),
  );

  return (
    <div style={{ width: "100%" }}>
      {showBar && (
        <div
          style={{
            width: "100%",
            height: "8px",
            backgroundColor: "#e2e8f0",
            borderRadius: "4px",
            overflow: "hidden",
            display: "flex",
          }}
        >
          <div
            style={{
              width: `${successPercent}%`,
              height: "100%",
              backgroundColor: "#16a34a",
              transition: "width 0.3s ease",
            }}
          />
          <div
            style={{
              width: `${failedPercent}%`,
              height: "100%",
              backgroundColor: "#dc2626",
              transition: "width 0.3s ease",
            }}
          />
        </div>
      )}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: "4px",
        }}
      >
        <span style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
            {done} / {total} subtasks
          </span>
          {failed > 0 && (
            <span style={{ fontSize: "0.75rem", color: "#dc2626" }}>
              ({failed} failed)
            </span>
          )}
        </span>
        <span
          style={{ fontSize: "0.75rem", color: "#64748b", fontWeight: 500 }}
        >
          {percent}%
        </span>
      </div>
    </div>
  );
}

// =============================================================================
// TaskTrackerSubtasksList
// =============================================================================

const SUBTASK_STATUS_SYMBOLS: Record<string, string> = {
  pending: "○",
  running: "◎",
  completed: "✓",
  failed: "✗",
  cancelled: "⏭",
  retrying: "◎",
};

const SUBTASK_STATUS_COLORS: Record<string, string> = {
  pending: "#94a3b8",
  running: "#2563eb",
  completed: "#16a34a",
  failed: "#dc2626",
  cancelled: "#ea580c",
  retrying: "#2563eb",
};

interface TaskTrackerSubtasksListProps {
  /** Per-subtask execution states keyed by Celery task ID. */
  tasks: Record<string, TaskExecutionState>;
  /** Whether to show in compact mode. */
  compact?: boolean;
  /** Maximum number of subtasks to show before truncating. */
  maxVisible?: number;
}

/**
 * Renders per-subtask execution states from the TrackerState.tasks dict.
 *
 * Each entry shows: status symbol · title or truncated task ID · error (if failed).
 * Sorted by relevance: running → failed → pending → completed.
 */
export function TaskTrackerSubtasksList({
  tasks,
  compact = false,
  maxVisible = 10,
}: TaskTrackerSubtasksListProps) {
  injectStyles();

  const entries = Object.entries(tasks);
  if (entries.length === 0) return null;

  const ORDER: Record<string, number> = {
    running: 0,
    retrying: 1,
    failed: 2,
    pending: 3,
    completed: 4,
    cancelled: 5,
  };
  const sorted = [...entries].sort(
    ([, a], [, b]) => (ORDER[a.status] ?? 99) - (ORDER[b.status] ?? 99),
  );

  const truncated = sorted.length > maxVisible;
  const visible = truncated ? sorted.slice(0, maxVisible) : sorted;
  const hiddenCount = sorted.length - visible.length;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: compact ? "4px" : "8px",
      }}
    >
      {visible.map(([taskId, state]) => {
        const color = SUBTASK_STATUS_COLORS[state.status] ?? FALLBACK_COLOR;
        const symbol = SUBTASK_STATUS_SYMBOLS[state.status] ?? "○";
        const isRunning =
          state.status === "running" || state.status === "retrying";
        const label = state.title || `${taskId.slice(0, 8)}…`;

        return (
          <div
            key={taskId}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: "8px",
              minHeight: "20px",
            }}
          >
            {/* Status indicator */}
            <span
              style={{
                color,
                flexShrink: 0,
                width: "16px",
                textAlign: "center",
                fontSize: compact ? "0.8rem" : "0.9rem",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                marginTop: "1px",
              }}
            >
              {isRunning ? <Spinner size="sm" /> : symbol}
            </span>

            {/* Label + error */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <span
                style={{
                  fontSize: compact ? "0.75rem" : "0.875rem",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  display: "block",
                }}
              >
                {label}
              </span>
              {state.status === "failed" && state.error_message && (
                <span
                  style={{
                    fontSize: "0.75rem",
                    color: "#dc2626",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    display: "block",
                  }}
                >
                  {state.error_message.length > 80
                    ? `${state.error_message.slice(0, 80)}…`
                    : state.error_message}
                </span>
              )}
            </div>

            {/* Duration for completed subtasks */}
            {state.status === "completed" &&
              state.started_at &&
              state.finished_at && (
                <span
                  style={{
                    fontSize: "0.75rem",
                    color: "#64748b",
                    flexShrink: 0,
                  }}
                >
                  {formatDuration(
                    (new Date(state.finished_at).getTime() -
                      new Date(state.started_at).getTime()) /
                      1000,
                  )}
                </span>
              )}
          </div>
        );
      })}
      {truncated && (
        <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
          +{hiddenCount} more subtask{hiddenCount !== 1 ? "s" : ""}…
        </span>
      )}
    </div>
  );
}

// =============================================================================
// TaskTrackerSteps
// =============================================================================

interface TaskTrackerStepsProps {
  steps: TrackedTaskStep[];
  compact?: boolean;
}

export function TaskTrackerSteps({
  steps,
  compact = false,
}: TaskTrackerStepsProps) {
  if (steps.length === 0) return null;

  injectStyles();

  const sortedSteps = [...steps].sort((a, b) => a.order - b.order);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: compact ? "4px" : "8px",
      }}
    >
      {sortedSteps.map((step) => {
        const color = STEP_STATUS_COLORS[step.status] ?? FALLBACK_COLOR;
        const symbol = STEP_STATUS_SYMBOLS[step.status] ?? "○";
        const isRunning = step.status === "running";

        return (
          <div
            key={step.name}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              opacity: step.status === "pending" ? 0.6 : 1,
            }}
          >
            {/* Status indicator */}
            <span
              style={{
                color,
                flexShrink: 0,
                width: "16px",
                textAlign: "center",
                fontSize: compact ? "0.8rem" : "0.9rem",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {isRunning ? <Spinner size="sm" /> : symbol}
            </span>

            {/* Label */}
            <span
              style={{
                flex: 1,
                fontSize: compact ? "0.75rem" : "0.875rem",
              }}
            >
              {step.label || step.name}
            </span>

            {/* Duration or progress */}
            {step.status === "completed" &&
              step.started_at &&
              step.finished_at && (
                <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
                  {formatDuration(
                    (new Date(step.finished_at).getTime() -
                      new Date(step.started_at).getTime()) /
                      1000,
                  )}
                </span>
              )}

            {step.status === "running" && step.progress_total > 0 && (
              <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
                {step.progress_current}/{step.progress_total}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// =============================================================================
// TrackedTaskCard
// =============================================================================

interface TrackedTaskCardProps {
  trackedTask: TrackedTaskListItem | TrackedTaskDetail;
  showSteps?: boolean;
}

export function TrackedTaskCard({
  trackedTask,
  showSteps = false,
}: TrackedTaskCardProps) {
  const hasProgress = trackedTask.progress_total > 0;
  const hasSubtasks = trackedTask.subtasks_total > 0;
  const isDetail = "steps" in trackedTask;
  const color = STATUS_COLORS[trackedTask.status] ?? FALLBACK_COLOR;

  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid #e2e8f0",
        borderRadius: "8px",
        backgroundColor: "#fafafa",
        transition: "border-color 0.2s",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "8px",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: "0.875rem", fontWeight: 500 }}>
            {trackedTask.name || trackedTask.tracked_task_type}
          </span>
          <TaskTrackerStatusBadge status={trackedTask.status} />
        </span>

        {trackedTask.started_at && (
          <span
            title={`Started at ${formatTime(trackedTask.started_at)}`}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "4px",
              fontSize: "0.75rem",
              color: "#64748b",
            }}
          >
            ⏱ {formatDuration(trackedTask.duration_seconds)}
          </span>
        )}
      </div>

      {/* Progress */}
      {hasProgress && (
        <div style={{ marginBottom: "8px" }}>
          <TaskTrackerProgressBar
            current={trackedTask.progress_current}
            total={trackedTask.progress_total}
            message={
              isDetail
                ? (trackedTask as TrackedTaskDetail).progress_message
                : undefined
            }
            color={color}
          />
        </div>
      )}

      {/* Subtasks */}
      {hasSubtasks && (
        <div style={{ marginBottom: "8px" }}>
          <TaskTrackerSubtasksProgress
            total={trackedTask.subtasks_total}
            completed={trackedTask.subtasks_completed}
            failed={trackedTask.subtasks_failed}
          />
        </div>
      )}

      {/* Steps */}
      {showSteps &&
        isDetail &&
        (trackedTask as TrackedTaskDetail).steps.length > 0 && (
          <div
            style={{
              marginTop: "12px",
              paddingTop: "12px",
              borderTop: "1px solid #e2e8f0",
            }}
          >
            <TaskTrackerSteps
              steps={(trackedTask as TrackedTaskDetail).steps}
              compact
            />
          </div>
        )}

      {/* Error message */}
      {trackedTask.status === "failed" &&
        isDetail &&
        (trackedTask as TrackedTaskDetail).error_message && (
          <div
            style={{
              marginTop: "8px",
              padding: "8px",
              backgroundColor: "#fef2f2",
              borderRadius: "4px",
              fontSize: "0.75rem",
              color: "#dc2626",
            }}
          >
            {(trackedTask as TrackedTaskDetail).error_message}
          </div>
        )}
    </div>
  );
}

// =============================================================================
// TaskTrackerList
// =============================================================================

interface TaskTrackerListProps {
  trackedTasks: TrackedTaskListItem[];
  emptyMessage?: string;
}

export function TaskTrackerList({
  trackedTasks,
  emptyMessage = "No tracked tasks found",
}: TaskTrackerListProps) {
  if (trackedTasks.length === 0) {
    return (
      <div style={{ padding: "16px", textAlign: "center" }}>
        <span style={{ fontSize: "0.875rem", color: "#64748b" }}>
          {emptyMessage}
        </span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      {trackedTasks.map((trackedTask) => (
        <TrackedTaskCard key={trackedTask.id} trackedTask={trackedTask} />
      ))}
    </div>
  );
}
