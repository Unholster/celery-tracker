const BASE = "/api/tracker";
const LOGS_BASE = "/api/tracker/logs";

export interface CeleryTask {
  name: string;
  description: string;
}

export interface RunTaskResult {
  tracker_id: string;
  task_name: string;
}

export interface TrackedTask {
  id: string;
  tracked_task_type: string;
  name: string;
  status: string;
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

export async function fetchCeleryTasks(): Promise<CeleryTask[]> {
  const res = await fetch(`${BASE}/celery-tasks`);
  if (!res.ok)
    throw new Error(`Failed to fetch celery tasks: ${res.statusText}`);
  return res.json();
}

export async function runCeleryTask(
  taskName: string,
  args: unknown[] = [],
  kwargs: Record<string, unknown> = {},
): Promise<RunTaskResult> {
  const res = await fetch(`${BASE}/celery-tasks/${taskName}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ args, kwargs }),
  });
  if (!res.ok) throw new Error(`Failed to run task: ${res.statusText}`);
  return res.json();
}

export async function fetchTrackedTasks(): Promise<TrackedTask[]> {
  const res = await fetch(`${BASE}/tracked-tasks`);
  if (!res.ok)
    throw new Error(`Failed to fetch tracked tasks: ${res.statusText}`);
  return res.json();
}

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
}

export async function fetchWorkerLogs(
  limit: number = 100,
): Promise<LogEntry[]> {
  const res = await fetch(`${LOGS_BASE}/worker?limit=${limit}`);
  if (!res.ok)
    throw new Error(`Failed to fetch worker logs: ${res.statusText}`);
  return res.json();
}
