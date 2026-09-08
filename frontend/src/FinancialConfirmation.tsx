import { useEffect, useId, useRef, useState, type ReactNode } from "react";

interface Props {
  title: string;
  consequence: string;
  actionLabel: string;
  noticeId: string;
  busy: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children: ReactNode;
}

export function FinancialConfirmation({
  title,
  consequence,
  actionLabel,
  noticeId,
  busy,
  confirmDisabled = false,
  onConfirm,
  onCancel,
  children,
}: Props) {
  const heading = useId(),
    description = useId();
  const dialog = useRef<HTMLElement>(null);
  const sent = useRef(false);
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const element = dialog.current;
    element?.focus();
    const keepFocus = (event: FocusEvent) => {
      if (
        event.target instanceof Node &&
        element &&
        !element.contains(event.target)
      )
        element.focus();
    };
    document.addEventListener("focusin", keepFocus);
    return () => {
      document.removeEventListener("focusin", keepFocus);
      if (opener?.isConnected && !opener.matches(":disabled")) opener.focus();
      else document.getElementById(noticeId)?.focus();
    };
  }, [noticeId]);
  const locked = busy || submitted;
  return (
    <div className="financial-confirmation-backdrop">
      <section
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={heading}
        aria-describedby={description}
        tabIndex={-1}
        className="information-card financial-confirmation"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            if (!locked) onCancel();
            return;
          }
          if (event.key !== "Tab") return;
          const controls = [
            ...(dialog.current?.querySelectorAll<HTMLElement>(
              "button, a[href], input, select, textarea, [tabindex]",
            ) ?? []),
          ].filter(
            (control) =>
              control.tabIndex >= 0 &&
              !control.matches(":disabled") &&
              !control.closest('[hidden], [aria-hidden="true"]'),
          );
          const first = controls[0],
            last = controls.at(-1),
            active = document.activeElement;
          if (!first) {
            event.preventDefault();
            dialog.current?.focus();
          } else if (
            event.shiftKey &&
            (active === first || active === dialog.current)
          ) {
            event.preventDefault();
            last?.focus();
          } else if (
            !event.shiftKey &&
            (active === last || active === dialog.current)
          ) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <h3 id={heading}>{title}</h3>
        <p id={description}>{consequence}</p>
        {children}
        {locked && (
          <p role="status">
            Checking this action. Wait for its recorded outcome.
          </p>
        )}
        <div className="button-row">
          <button type="button" onClick={onCancel} disabled={locked}>
            Cancel
          </button>
          <button
            type="button"
            disabled={locked || confirmDisabled}
            onClick={() => {
              if (busy || confirmDisabled || sent.current) return;
              sent.current = true;
              setSubmitted(true);
              onConfirm();
            }}
          >
            {actionLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
