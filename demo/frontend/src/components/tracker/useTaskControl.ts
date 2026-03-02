/* eslint-disable react-hooks/refs -- intentional render-phase ref reads/writes: prevTaskRef bridges task transitions to prevent null flashes */
/**
 * useTaskControl - Universal hook for triggering and tracking async Celery tasks.
 *
 * Replaces scattered patterns of:
 *   - useState(activeTaskId) + useMutation + useTrackedTask + useEffect
 *
 * With a single composable hook that handles:
 *   1. Triggering the task via a mutation
 *   2. Polling the TrackedTask for progress (by TrackedTask UUID)
 *   3. Recovering state on page reload (via useLatestTrackedTask)
 *   4. Calling callbacks on completion/error
 *   5. Providing derived state (isRunning, isQueued, isTerminal)
 *
 * Adapted from gna-benefits-recon's useTaskControl for the celery-tracker demo.
 * Removes @seisveinte/react and auth dependencies — works with plain React + React Query.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  useTrackedTask,
  useLatestTrackedTask,
  isActiveStatus,
  isTerminalStatus,
  type TrackedTaskDetail,
  type TrackedTaskStatus,
} from "./taskTracker";

// =============================================================================
// Types
// =============================================================================

export interface TriggerResponse {
  task_id: string;
  status: string;
  message?: string;
}

export interface UseTaskControlOptions<TParams = void> {
  /** The tracked_task_type string (e.g., "demoproject.celery.meditate") */
  trackedTaskType: string;

  /** Function that calls the trigger API endpoint. Must return { task_id, status }. */
  triggerFn: (params: TParams) => Promise<TriggerResponse>;

  /** Called when the task reaches a terminal success state (completed, partial_success). */
  onComplete?: (task: TrackedTaskDetail) => void;

  /** Called when the task reaches a terminal failure state (failed). */
  onError?: (task: TrackedTaskDetail) => void;

  /** Called when the task reaches any terminal state. */
  onSettled?: (task: TrackedTaskDetail) => void;

  /**
   * Query keys to invalidate when the task completes (any terminal state).
   * Useful for refreshing data that the task modified.
   */
  invalidateOnComplete?: readonly (readonly unknown[])[];

  /**
   * Whether to recover the latest task of this type on mount (for page reload).
   * Defaults to true.
   */
  recoverOnMount?: boolean;

  /**
   * Metadata key-value pairs to scope task recovery to a specific entity.
   * When provided, only tasks whose metadata contains ALL the given key-value pairs
   * will be recovered on mount.
   */
  metadataFilter?: Record<string, unknown>;

  /**
   * Polling interval (ms) for the active task detail query (useTrackedTask).
   * Lower values give snappier progress updates but cost more HTTP requests.
   * Default: 2000 (2s).
   */
  activePollingInterval?: number;

  /**
   * Polling interval (ms) for the latest task recovery query (useLatestTrackedTask).
   * Default: 5000 (5s).
   */
  recoveryPollingInterval?: number;
}

export interface UseTaskControlReturn<TParams = void> {
  /** Trigger the task. Calling this when already running is a no-op. */
  trigger: (params: TParams) => void;

  /** The current TrackedTask detail, or null if none. */
  task: TrackedTaskDetail | null;

  /** Whether the task is in an active state (pending, running, retrying). */
  isRunning: boolean;

  /** Whether the task is queued (activeTaskId set but task not found yet). */
  isQueued: boolean;

  /** Whether the task is in a terminal state (completed, failed, cancelled, partial_success). */
  isTerminal: boolean;

  /** Whether the task appears stale (active status but no updates for a long time). */
  isStale: boolean;

  /** Whether the trigger mutation is currently pending. */
  isTriggerPending: boolean;

  /** Error message from the task, if any. */
  error: string | null;

  /** Error from the trigger mutation, if any. */
  triggerError: Error | null;

  /** The tracked task ID (UUID), if any. */
  activeTaskId: string | null;

  /** Reset the task control state (clear active task). */
  reset: () => void;

  /**
   * Force-enable recovery (useLatestTrackedTask) even when recoverOnMount is false.
   * Useful for lazy recovery: the component doesn't poll on mount, but starts
   * polling when the user explicitly requests progress.
   */
  recover: () => void;

  /** Whether recovery has been requested but no task has been found yet. */
  isRecovering: boolean;

  /**
   * Whether recovery was attempted and completed but found no tracked task.
   * When the domain model reports an active state but this is true, the task
   * is effectively stalled.
   */
  isRecoveryEmpty: boolean;

  /**
   * Whether the initial mount recovery is still loading.
   * True before the first latestTask query resolves. Used to show a loading
   * indicator instead of flashing an incorrect fallback status on page load.
   */
  isInitialLoading: boolean;
}

// =============================================================================
// Hook
// =============================================================================

export function useTaskControl<TParams = void>(
  options: UseTaskControlOptions<TParams>,
): UseTaskControlReturn<TParams> {
  const {
    trackedTaskType,
    triggerFn,
    onComplete,
    onError,
    onSettled,
    invalidateOnComplete,
    recoverOnMount = true,
    metadataFilter,
    activePollingInterval,
    recoveryPollingInterval,
  } = options;

  const queryClient = useQueryClient();

  // Active task ID (TrackedTask UUID, not Celery task ID)
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  // Lazy recovery: enabled when recover() is called explicitly
  const [forceRecovery, setForceRecovery] = useState(false);

  // Track whether callbacks have fired for the current task
  const settledRef = useRef<string | null>(null);

  // Bridge ref: preserves the last known task during the
  // latestTask → activeTask transition so the UI doesn't flicker.
  // Reading/writing this ref during render is intentional — it acts as a
  // synchronous cache so the consumer never sees a null flash between
  // two valid task objects.
  const prevTaskRef = useRef<TrackedTaskDetail | null>(null);

  // Poll the active task by TrackedTask UUID
  const { data: activeTask, error: activeTaskError } = useTrackedTask(
    activeTaskId,
    activePollingInterval != null
      ? { activeInterval: activePollingInterval }
      : undefined,
  );

  // Recover the latest task of this type on mount (survives page reload)
  // or when recover() is called explicitly (lazy recovery).
  // Disable this query when activeTaskId is set — useTrackedTask already
  // handles polling for the active task.
  const latestTaskEnabled = !activeTaskId && (recoverOnMount || forceRecovery);
  const { data: latestTask, isFetching: isLatestTaskFetching } =
    useLatestTrackedTask(
      latestTaskEnabled ? trackedTaskType : null,
      metadataFilter,
      recoveryPollingInterval != null
        ? { activeInterval: recoveryPollingInterval }
        : undefined,
    );

  // Use active task if available, otherwise fall back to latest.
  // When activeTaskId is set we are tracking a specific (usually new) task —
  // latestTask is stale data from a previous query and MUST NOT leak through.
  const rawTask = activeTask ?? (activeTaskId ? null : (latestTask ?? null));

  if (rawTask) prevTaskRef.current = rawTask;
  const task = rawTask ?? prevTaskRef.current;
  const taskStatus = task?.status as TrackedTaskStatus | undefined;

  // Trigger mutation
  const triggerMutation = useMutation({
    mutationFn: triggerFn,
    onSuccess: (data) => {
      const trackedTaskQueryKey = ["tracked-task", data.task_id] as const;

      // If a previous task with the same ID existed, clear stale cache
      queryClient.removeQueries({ queryKey: trackedTaskQueryKey, exact: true });
      void queryClient.invalidateQueries({
        queryKey: trackedTaskQueryKey,
        exact: true,
      });

      // Clear the previous task bridge so the UI shows "Queued" for the
      // new task instead of clinging to the old task's status.
      prevTaskRef.current = null;
      setActiveTaskId(data.task_id);
      settledRef.current = null;
    },
  });

  // Derived state
  const isStale = task?.is_stale ?? false;
  const isQueued = !!(activeTaskId && !activeTask && !activeTaskError);
  const isRunning =
    triggerMutation.isPending ||
    isQueued ||
    !!(taskStatus && isActiveStatus(taskStatus) && !isStale);
  const isTerminal = !!(taskStatus && isTerminalStatus(taskStatus));
  const error =
    task?.status === "failed" ? task.error_message || "Task failed" : null;

  // Fire callbacks when task reaches terminal state
  useEffect(() => {
    if (!task || !isTerminal) return;
    if (settledRef.current === task.id) return;
    settledRef.current = task.id;

    if (task.status === "completed" || task.status === "partial_success") {
      onComplete?.(task);
    } else if (task.status === "failed") {
      onError?.(task);
    }

    onSettled?.(task);

    if (invalidateOnComplete) {
      for (const queryKey of invalidateOnComplete) {
        queryClient.invalidateQueries({ queryKey });
      }
    }
  }, [
    task,
    isTerminal,
    onComplete,
    onError,
    onSettled,
    invalidateOnComplete,
    queryClient,
  ]);

  // Auto-expand: when recovered task is active, track it.
  // Skip stale tasks — they appear active but haven't been updated for a long time.
  useEffect(() => {
    if (
      (recoverOnMount || forceRecovery) &&
      latestTask &&
      !activeTaskId &&
      isActiveStatus(latestTask.status as TrackedTaskStatus) &&
      !latestTask.is_stale
    ) {
      setActiveTaskId(latestTask.id);
    }
  }, [recoverOnMount, forceRecovery, latestTask, activeTaskId]);

  const trigger = useCallback(
    (params: TParams) => {
      if (isRunning) return;
      triggerMutation.mutate(params);
    },
    [isRunning, triggerMutation],
  );

  const reset = useCallback(() => {
    setActiveTaskId(null);
    setForceRecovery(false);
    settledRef.current = null;
    prevTaskRef.current = null;
  }, []);

  const recover = useCallback(() => {
    if (!activeTaskId && !forceRecovery) {
      setForceRecovery(true);
    }
  }, [activeTaskId, forceRecovery]);

  const isRecovering =
    forceRecovery &&
    !rawTask &&
    !prevTaskRef.current &&
    (isLatestTaskFetching || latestTask === undefined);

  const isRecoveryEmpty =
    (recoverOnMount || forceRecovery) &&
    !task &&
    !isLatestTaskFetching &&
    latestTask === null;

  const isInitialLoading =
    recoverOnMount && !activeTaskId && !task && latestTask === undefined;

  return {
    trigger,
    task: task ?? null,
    isRunning,
    isQueued,
    isTerminal,
    isStale,
    isTriggerPending: triggerMutation.isPending,
    error,
    triggerError: triggerMutation.error,
    activeTaskId,
    reset,
    recover,
    isRecovering,
    isRecoveryEmpty,
    isInitialLoading,
  };
}
