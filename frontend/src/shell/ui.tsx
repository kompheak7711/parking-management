// V1-058 R2: small pieces the rebuilt screens share (mock-up app.css: chip, kpi, dialog).

import { FormEvent, ReactNode, useEffect, useId, useRef } from "react";

import { Icon, type ShellIcon } from "./icons";

export type Tone = "ok" | "warn" | "err" | "info" | "neutral";

export function Chip({
  tone,
  icon,
  children,
}: {
  tone: Tone;
  icon?: ShellIcon;
  children: ReactNode;
}) {
  return (
    <span className={`ui-chip ${tone}`}>
      {icon !== undefined && <Icon name={icon} small />}
      {children}
    </span>
  );
}

/** A count card that filters a list; pressed while its filter is on. */
export function CountCard({
  icon,
  tone,
  label,
  value,
  note,
  pressed,
  onPress,
  valueText,
}: {
  icon: ShellIcon;
  tone: Tone | "brand" | "none";
  label: string;
  value: number;
  note: string;
  pressed: boolean;
  onPress: () => void;
  /** How the value is written, such as "$1,250.00"; the plain number by default. */
  valueText?: string;
}) {
  const shown = valueText ?? String(value);
  return (
    <button
      aria-label={`${label}: ${shown}. ${note}`}
      aria-pressed={pressed}
      className={`ui-kpi ${value === 0 ? "none" : tone}`}
      onClick={onPress}
      type="button"
    >
      <span className="ui-kpi-label">
        <span className="ui-kpi-icon">
          <Icon name={icon} small />
        </span>
        {label}
      </span>
      <span className="ui-kpi-value ui-num">{shown}</span>
      <span className="ui-kpi-note">{note}</span>
    </button>
  );
}

/**
 * A dialog over the page. With `onSubmit` its body is a form with Cancel and a submit button;
 * without it there is one button that closes it. Escape closes it too.
 */
export function Dialog({
  title,
  children,
  onClose,
  onSubmit,
  submitLabel,
  closeLabel,
  busy = false,
  wide = false,
  actions,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
  submitLabel?: string;
  closeLabel: string;
  busy?: boolean;
  /** Up to 820px, for a table with many columns. */
  wide?: boolean;
  /** More buttons after Close, for a dialog without a form (such as Reject and Confirm). */
  actions?: ReactNode;
}) {
  const headingId = useId();
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  const working = useRef(busy);
  useEffect(() => {
    close.current = onClose;
    working.current = busy;
  });

  useEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const focusable = () =>
      Array.from(
        box.current?.querySelectorAll<HTMLElement>(
          "input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])",
        ) ?? [],
      ).filter(
        (element) =>
          !(
            element instanceof HTMLInputElement &&
            element.type === "radio" &&
            !element.checked &&
            box.current?.querySelector(
              `input[type="radio"][name="${element.name}"]:checked`,
            ) != null
          ),
      );
    focusable()[0]?.focus();
    function onKey(event: KeyboardEvent) {
      // Escape works like Cancel, so not while a save is running.
      if (event.key === "Escape" && !working.current) close.current();
      // Tab stays inside the dialog.
      if (event.key === "Tab") {
        const items = focusable();
        const first = items[0];
        const last = items[items.length - 1];
        if (first === undefined || last === undefined) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener?.isConnected === true) opener.focus();
    };
  }, []);

  const buttons = (
    <div className="ui-dlg-buttons">
      <button
        className="ui-btn"
        disabled={busy}
        onClick={onClose}
        type="button"
      >
        {closeLabel}
      </button>
      {actions}
      {onSubmit !== undefined && (
        <button className="ui-btn primary" disabled={busy} type="submit">
          {submitLabel}
        </button>
      )}
    </div>
  );
  return (
    <div className="ui-dlg-back">
      <div
        aria-labelledby={headingId}
        aria-modal="true"
        className={wide ? "ui-dlg wide" : "ui-dlg"}
        ref={box}
        role="dialog"
      >
        <h2 id={headingId}>{title}</h2>
        {onSubmit === undefined ? (
          <>
            {children}
            {buttons}
          </>
        ) : (
          <form className="ui-form" noValidate onSubmit={onSubmit}>
            {children}
            {buttons}
          </form>
        )}
      </div>
    </div>
  );
}
