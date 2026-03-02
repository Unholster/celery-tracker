/**
 * Task Tracker API types and hooks.
 *
 * Provides types and React Query hooks for the celery-tracker backend.
 * Adapted from the gna-benefits-recon taskTracker service to work with
 * the celery-tracker demo API (no auth, simplified endpoints).
 */

import { useQuery } from "@tanstack/react-query";

const API_BASE = "/api/tracker";

// =============================================================================
// Types
// =============================================================================

export type TrackedTaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "partial_success"
  | "retrying";

export type TrackedTaskStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "skipped"
  | "failed";

export interface TrackedTaskStep {
  name: string;
  label: string;
  order: number;
  status: TrackedTaskStepStatus;
  started_at: string | null;
  finished_at: string | null;
  progress_current: number;
  progress_total: number;
  progress_message: string;
  progress_percent: number | null;
}

/**
 * Per-subtask execution state, keyed by Celery task ID in the `tasks` dict.
 * Maps directly to the TrackerState.tasks entries from celery-tracker.
 */
export interface TaskExecutionState {
  title: string | null;
  status: TrackedTaskStatus;
  started_at: string | null;
  finished_at: string | null;
  error_message: string;
  result: Record<string, unknown> | null;
}

export interface TrackedTaskListItem {
  id: string;
  tracked_task_type: string;
  name: string;
  status: TrackedTaskStatus;
  progress_current: number;
  progress_total: number;
  progress_percent: number | null;
  subtasks_total: number;
  subtasks_completed: number;
  subtasks_failed: number;
  subtasks_progress_percent: number | null;
  created_at: string;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  is_stale: boolean;
  error_message: string;
  metadata: Record<string, unknown>;
}

export interface TrackedTaskDetail extends TrackedTaskListItem {
  celery_task_id: string | null;
  progress_message: string;
  result: Record<string, unknown> | null;
  steps: TrackedTaskStep[];
  /** Per-subtask execution states keyed by Celery task ID. */
  tasks: Record<string, TaskExecutionState>;
  parent_task_id: string | null;
}

// =============================================================================
// API Functions
// =============================================================================

async function fetchTrackedTaskById(
  trackedTaskId: string,
): Promise<TrackedTaskDetail> {
  const response = await fetch(`${API_BASE}/tracked-tasks/${trackedTaskId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch tracked task: ${response.statusText}`);
  }
  return response.json();
}

async function fetchTrackedTasks(): Promise<TrackedTaskListItem[]> {
  const response = await fetch(`${API_BASE}/tracked-tasks`);
  if (!response.ok) {
    throw new Error(`Failed to fetch tracked tasks: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Fetch the most recent tracked task of a given type (any status).
 *
 * The celery-tracker list endpoint returns all tasks (no pagination or
 * type filter), so we filter and sort client-side.
 *
 * @param metadataFilter - Optional key-value pairs to filter by metadata contents.
 */
async function fetchLatestTrackedTaskByType(
  trackedTaskType: string,
  metadataFilter?: Record<string, unknown>,
): Promise<TrackedTaskDetail | null> {
  const allTasks = await fetchTrackedTasks();

  // Filter by type
  let matching = allTasks.filter(
    (t) => t.tracked_task_type === trackedTaskType,
  );

  // Filter by metadata if provided
  if (metadataFilter && Object.keys(metadataFilter).length > 0) {
    matching = matching.filter((t) =>
      Object.entries(metadataFilter).every(
        ([key, value]) => t.metadata[key] === value,
      ),
    );
  }

  if (matching.length === 0) return null;

  // Sort by created_at descending and take the first
  matching.sort(
    (a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  return fetchTrackedTaskById(matching[0].id);
}

export async function cancelTrackedTask(
  trackedTaskId: string,
): Promise<{ id: string; status: string; revoked_task_ids: string[] }> {
  const response = await fetch(
    `${API_BASE}/tracked-tasks/${trackedTaskId}/cancel`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(
      error.detail || `Failed to cancel tracked task: ${response.statusText}`,
    );
  }
  return response.json();
}

// =============================================================================
// Helpers
// =============================================================================

/** Statuses that indicate the task is still active and should be polled. */
const ACTIVE_STATUSES: Set<TrackedTaskStatus> = new Set([
  "pending",
  "running",
  "retrying",
]);

/** Whether a task status is terminal (no further updates expected). */
export function isTerminalStatus(status: TrackedTaskStatus): boolean {
  return !ACTIVE_STATUSES.has(status);
}

/** Whether a task status is active (still running, should poll). */
export function isActiveStatus(status: TrackedTaskStatus): boolean {
  return ACTIVE_STATUSES.has(status);
}

// =============================================================================
// React Query Hooks
// =============================================================================

/**
 * Hook to fetch a single tracked task by ID.
 *
 * Polls while the task is active, stops when terminal.
 *
 * @param options.activeInterval - Polling interval (ms) while task is active. Default: 2000.
 */
export function useTrackedTask(
  trackedTaskId: string | null,
  options?: { activeInterval?: number },
) {
  const activeInterval = options?.activeInterval ?? 2000;

  return useQuery({
    queryKey: ["tracked-task", trackedTaskId],
    queryFn: () => fetchTrackedTaskById(trackedTaskId!),
    enabled: !!trackedTaskId,
    refetchInterval: (query) => {
      const trackedTask = query.state.data;
      if (trackedTask && isActiveStatus(trackedTask.status)) {
        return activeInterval;
      }
      return false;
    },
  });
}

/**
 * Hook to fetch the latest tracked task of a given type (any status).
 *
 * Useful for showing results of the most recent task, even if completed.
 * Polls while a task is active.
 *
 * @param metadataFilter - Optional key-value pairs to scope recovery to a specific entity.
 * @param options.activeInterval - Polling interval (ms) while task is active. Default: 5000.
 */
export function useLatestTrackedTask(
  trackedTaskType: string | null,
  metadataFilter?: Record<string, unknown>,
  options?: { activeInterval?: number },
) {
  const activeInterval = options?.activeInterval ?? 5000;

  return useQuery({
    queryKey: [
      "tracked-task",
      "latest",
      trackedTaskType,
      metadataFilter ?? null,
    ],
    queryFn: () =>
      fetchLatestTrackedTaskByType(trackedTaskType!, metadataFilter),
    enabled: !!trackedTaskType,
    refetchInterval: (query) => {
      const trackedTask = query.state.data;
      if (trackedTask && isActiveStatus(trackedTask.status)) {
        return activeInterval;
      }
      return false;
    },
  });
}

/**
 * Hook to fetch all tracked tasks.
 */
export function useTrackedTasks(refetchInterval: number = 3000) {
  return useQuery({
    queryKey: ["tracked-tasks"],
    queryFn: fetchTrackedTasks,
    refetchInterval,
  });
}
