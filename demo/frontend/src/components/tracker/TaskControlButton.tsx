/**
 * TaskControlButton - Universal button for triggering async Celery tasks.
 *
 * Integrates with useTaskControl to show the correct state:
 * - Idle: shows label with optional icon
 * - Running: shows spinner with runningLabel
 * - Disabled when task is active
 *
 * Supports three variants:
 * - "button": Full button (default) - for page headers and action bars
 * - "icon": Icon-only button - for compact actions (e.g., refresh icon)
 * - "dropdown-item": For use inside dropdown menus (renders a <li> element)
 *
 * Adapted from gna-benefits-recon's TaskControlButton, replacing
 * @seisveinte/react and lucide-react with native elements and CSS.
 */

import type { UseTaskControlReturn } from "./useTaskControl";

// =============================================================================
// Spinner (CSS-only, matches TaskTrackerProgress)
// =============================================================================

let stylesInjected = false;

function injectStyles() {
  if (stylesInjected) return;
  stylesInjected = true;

  const style = document.createElement("style");
  style.textContent = `
    @keyframes tcb-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    .tcb-spinner {
      display: inline-block;
      border: 2px solid currentColor;
      border-top-color: transparent;
      border-radius: 50%;
      animation: tcb-spin 0.8s linear infinite;
      flex-shrink: 0;
    }
  `;
  document.head.appendChild(style);
}

function Spinner({ size = 14 }: { size?: number }) {
  injectStyles();
  return (
    <span
      className="tcb-spinner"
      style={{ width: `${size}px`, height: `${size}px` }}
    />
  );
}

// =============================================================================
// Types
// =============================================================================

interface TaskControlButtonBaseProps {
  /** Label shown when idle */
  label: string;
  /** Label shown when task is running (defaults to label + "...") */
  runningLabel?: string;
  /** The task control instance from useTaskControl */
  taskControl: UseTaskControlReturn<unknown>;
  /** Whether the button should be disabled for external reasons */
  disabled?: boolean;
}

interface TaskControlButtonButtonProps extends TaskControlButtonBaseProps {
  variant?: "button";
  /** Button size: "1" = small, "2" = medium (default), "3" = large */
  size?: "1" | "2" | "3";
  /** Optional icon (ReactNode) to show before label */
  icon?: React.ReactNode;
}

interface TaskControlButtonIconProps extends TaskControlButtonBaseProps {
  variant: "icon";
  /** Icon to show (required for icon variant) */
  icon: React.ReactNode;
  /** Button size: "1" = small, "2" = medium (default), "3" = large */
  size?: "1" | "2" | "3";
}

interface TaskControlButtonDropdownProps extends TaskControlButtonBaseProps {
  variant: "dropdown-item";
  /** Optional icon to show before label */
  icon?: React.ReactNode;
}

type TaskControlButtonProps =
  | TaskControlButtonButtonProps
  | TaskControlButtonIconProps
  | TaskControlButtonDropdownProps;

// =============================================================================
// Size maps
// =============================================================================

const BUTTON_PADDING: Record<string, string> = {
  "1": "4px 10px",
  "2": "6px 14px",
  "3": "8px 18px",
};

const BUTTON_FONT_SIZE: Record<string, string> = {
  "1": "0.8rem",
  "2": "0.875rem",
  "3": "0.9375rem",
};

const ICON_BUTTON_SIZE: Record<string, string> = {
  "1": "28px",
  "2": "32px",
  "3": "38px",
};

const SPINNER_SIZE: Record<string, number> = {
  "1": 12,
  "2": 14,
  "3": 16,
};

// =============================================================================
// Component
// =============================================================================

export function TaskControlButton(props: TaskControlButtonProps) {
  const {
    label,
    runningLabel,
    taskControl,
    disabled: externalDisabled,
    variant = "button",
  } = props;

  const isActive = taskControl.isRunning || taskControl.isQueued;
  const isDisabled = isActive || externalDisabled;
  const displayLabel = isActive ? (runningLabel ?? `${label}...`) : label;

  const handleClick = () => {
    if (!isDisabled) {
      taskControl.trigger(undefined as unknown);
    }
  };

  // ── Icon variant: compact icon-only button with title tooltip ──────
  if (variant === "icon") {
    const { icon, size = "2" } = props as TaskControlButtonIconProps;
    const dim = ICON_BUTTON_SIZE[size];
    const spinnerPx = SPINNER_SIZE[size];

    return (
      <button
        type="button"
        title={displayLabel}
        onClick={handleClick}
        disabled={isDisabled}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: dim,
          height: dim,
          padding: 0,
          border: "none",
          borderRadius: "6px",
          background: "none",
          cursor: isDisabled ? "not-allowed" : "pointer",
          color: "inherit",
          opacity: isDisabled && !isActive ? 0.5 : 1,
          transition: "background 120ms",
        }}
        onMouseEnter={(e) => {
          if (!isDisabled)
            e.currentTarget.style.backgroundColor = "rgba(0,0,0,0.06)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = "transparent";
        }}
      >
        {isActive ? <Spinner size={spinnerPx} /> : icon}
      </button>
    );
  }

  // ── Dropdown-item variant: for use inside a <ul> dropdown ──────────
  if (variant === "dropdown-item") {
    const { icon } = props as TaskControlButtonDropdownProps;

    return (
      <li
        role="menuitem"
        tabIndex={isDisabled ? -1 : 0}
        onClick={isDisabled ? undefined : handleClick}
        onKeyDown={(e) => {
          if (!isDisabled && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            handleClick();
          }
        }}
        aria-disabled={isDisabled || undefined}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "6px 12px",
          fontSize: "0.875rem",
          cursor: isDisabled ? "not-allowed" : "pointer",
          opacity: isDisabled ? 0.5 : 1,
          color: "inherit",
          listStyle: "none",
          borderRadius: "4px",
          transition: "background 120ms",
        }}
        onMouseEnter={(e) => {
          if (!isDisabled)
            e.currentTarget.style.backgroundColor = "rgba(0,0,0,0.06)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = "transparent";
        }}
      >
        {isActive ? <Spinner size={14} /> : icon}
        <span>{displayLabel}</span>
      </li>
    );
  }

  // ── Button variant (default): full button with icon and label ──────
  const { icon, size = "2" } = props as TaskControlButtonButtonProps;
  const spinnerPx = SPINNER_SIZE[size];

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isDisabled}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        padding: BUTTON_PADDING[size],
        fontSize: BUTTON_FONT_SIZE[size],
        fontWeight: 500,
        fontFamily: "inherit",
        lineHeight: 1.4,
        borderRadius: "6px",
        border: "1px solid rgba(128,128,128,0.3)",
        backgroundColor: "#f0f0f0",
        color: "inherit",
        cursor: isDisabled ? "not-allowed" : "pointer",
        opacity: isDisabled && !isActive ? 0.5 : 1,
        transition: "background-color 0.15s, border-color 0.15s",
        whiteSpace: "nowrap",
      }}
      onMouseEnter={(e) => {
        if (!isDisabled) {
          e.currentTarget.style.backgroundColor = "#e0e0e0";
          e.currentTarget.style.borderColor = "rgba(128,128,128,0.5)";
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = "#f0f0f0";
        e.currentTarget.style.borderColor = "rgba(128,128,128,0.3)";
      }}
    >
      {isActive ? <Spinner size={spinnerPx} /> : icon}
      {displayLabel}
    </button>
  );
}
