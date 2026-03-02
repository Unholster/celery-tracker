import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { runCeleryTask, fetchWorkerLogs, type LogEntry } from "./api";
import {
  useTaskControl,
  TaskControlButton,
  TaskProgressCard,
  type TriggerResponse,
  type UseTaskControlReturn,
} from "./components/tracker";

// =============================================================================
// Static task definitions
// =============================================================================

interface DemoTaskDef {
  name: string;
  label: string;
  level: string;
  description: string;
  observeHint: string;
  trackedTaskType: string;
}

const DEMO_TASKS: DemoTaskDef[] = [
  {
    name: "demoproject.celery.report_basic.generate_report_basic",
    label: "Basic",
    level: "Level 1",
    description:
      "A single task runs all five phases inside one function body. No steps, no subtasks — the tracker only knows pending / running / done.",
    observeHint:
      'You\'ll see "Processing\u2026" and then "Completed" with no intermediate detail.',
    trackedTaskType: "task",
  },
  {
    name: "demoproject.celery.report_stepped.generate_report_stepped",
    label: "Stepped",
    level: "Level 2",
    description:
      "Same single task, but each phase is wrapped in a tracked step. The steps list fills in as the task progresses.",
    observeHint:
      "Watch the steps checklist — each phase lights up as it starts and shows its duration when done.",
    trackedTaskType: "task",
  },
  {
    name: "report_chained",
    label: "Chained",
    level: "Level 3",
    description:
      "Each phase is its own Celery task in a chain. All five are stored at dispatch time and visible as PENDING immediately.",
    observeHint:
      "All five subtasks appear instantly. They transition one-by-one from pending → running → completed.",
    trackedTaskType: "chain",
  },
  {
    name: "report_fanout",
    label: "Fan-out",
    level: "Level 4",
    description:
      "Fetch data, then three analysis sections run in parallel (group), then compile and deliver. Combines chain, group, and chord.",
    observeHint:
      'The three "Analyze \u2026" subtasks run simultaneously. The progress bar shows completed vs total subtasks.',
    trackedTaskType: "group",
  },
];

// =============================================================================
// App
// =============================================================================

function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Celery Tracker Demo</h1>
        <p className="muted">
          Same process — <em>generate a quarterly sales report</em> — modelled
          four ways, from a simple black box to a fully observable fan-out
          pipeline.
        </p>
      </header>

      <div className="columns">
        <div className="col-left">
          {DEMO_TASKS.map((def) => (
            <TaskDemo key={def.name} def={def} />
          ))}
        </div>

        <div className="col-right">
          <h2>Worker Logs</h2>
          <WorkerLogs />
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// TaskDemo — one card per demo task
// =============================================================================

function TaskDemo({ def }: { def: DemoTaskDef }) {
  const taskControl = useTaskControl<void>({
    trackedTaskType: def.trackedTaskType,
    triggerFn: async (): Promise<TriggerResponse> => {
      const result = await runCeleryTask(def.name);
      return { task_id: result.tracker_id, status: "pending" };
    },
    invalidateOnComplete: [["tracked-tasks"]],
    recoverOnMount: false,
    activePollingInterval: 1000,
  });

  const { task, isQueued } = taskControl;
  const showProgress = !!(task || isQueued);

  return (
    <div className="task-demo">
      <div className="task-demo-header">
        <div>
          <span
            style={{
              fontSize: "0.7rem",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              color: "#64748b",
            }}
          >
            {def.level}
          </span>
          <h3 style={{ margin: 0 }}>{def.label}</h3>
        </div>
        <TaskControlButton
          label="Run"
          runningLabel="Running…"
          icon={<span>▶</span>}
          size="1"
          taskControl={taskControl as UseTaskControlReturn<unknown>}
        />
      </div>

      <p className="task-demo-description">{def.description}</p>
      <p
        style={{
          margin: "0 0 8px",
          fontSize: "0.75rem",
          color: "#64748b",
          fontStyle: "italic",
        }}
      >
        👁 {def.observeHint}
      </p>

      {showProgress && (
        <div className="task-demo-progress">
          <TaskProgressCard
            task={task}
            isQueued={isQueued}
            title={def.label}
            collapsible={false}
            renderResult={(t) =>
              t.result ? (
                <div
                  style={{
                    marginTop: "8px",
                    padding: "8px",
                    backgroundColor: "#f0fdf4",
                    borderRadius: "4px",
                    fontSize: "0.75rem",
                    color: "#166534",
                    fontFamily: "monospace",
                    wordBreak: "break-word",
                  }}
                >
                  <strong>Result:</strong> {JSON.stringify(t.result)}
                </div>
              ) : null
            }
          />
        </div>
      )}
      <pre style={{ fontSize: "0.8em", overflow: "hidden" }}>
        {JSON.stringify(task, null, 2)}
      </pre>
    </div>
  );
}

// =============================================================================
// WorkerLogs
// =============================================================================

const LEVEL_CLASS: Record<string, string> = {
  DEBUG: "log-debug",
  INFO: "log-info",
  WARNING: "log-warning",
  ERROR: "log-error",
  CRITICAL: "log-error",
};

function WorkerLogs() {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const wasAtBottomRef = useRef(true);

  const { data: logs, error } = useQuery({
    queryKey: ["worker-logs"],
    queryFn: () => fetchWorkerLogs(200),
    refetchInterval: 2000,
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const onScroll = () => {
      wasAtBottomRef.current =
        el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (wasAtBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const chronological = logs ? [...logs].reverse() : [];

  return (
    <>
      {error && <p className="error">Error: {(error as Error).message}</p>}
      <div className="log-viewer" ref={containerRef}>
        {chronological.length === 0 && <p className="muted">No logs yet.</p>}
        {chronological.map((entry: LogEntry, i: number) => (
          <div
            key={`${entry.timestamp}-${i}`}
            className={`log-line ${LEVEL_CLASS[entry.level] ?? ""}`}
          >
            <span className="log-time">
              {new Date(entry.timestamp).toLocaleTimeString()}
            </span>
            <span className="log-level">{entry.level.padEnd(8)}</span>
            <span className="log-msg">{entry.message}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </>
  );
}

export default App;
