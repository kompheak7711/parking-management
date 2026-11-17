// DL-243 answer 1: a finger signature on the tablet. The pad draws with the finger, a mouse or a
// pen and gives a PNG picture; the server keeps it with the inspection.

import { useEffect, useId, useRef, useState } from "react";

import type { Language } from "../signInText";
import { jt } from "./text";

export function SignaturePad({
  language,
  label,
  busy,
  onSave,
}: {
  language: Language;
  label: string;
  busy: boolean;
  onSave: (picture: Blob) => void;
}) {
  const id = useId();
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const drawing = useRef(false);
  const [drawn, setDrawn] = useState(false);
  const [empty, setEmpty] = useState(false);

  // The pad fills its box; the drawing keeps a sharp line on high-density screens.
  useEffect(() => {
    const pad = canvas.current;
    if (pad === null) return;
    const ratio = window.devicePixelRatio || 1;
    const box = pad.getBoundingClientRect();
    pad.width = Math.max(1, Math.round((box.width || 600) * ratio));
    pad.height = Math.max(1, Math.round((box.height || 200) * ratio));
    const context = pad.getContext("2d");
    if (context === null) return;
    context.scale(ratio, ratio);
    context.lineWidth = 2.5;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = "#252a28";
  }, []);

  const point = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  };

  const clear = () => {
    const pad = canvas.current;
    const context = pad?.getContext("2d") ?? null;
    if (pad !== null && context !== null) {
      context.save();
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, pad.width, pad.height);
      context.restore();
    }
    setDrawn(false);
  };

  return (
    <div className="ji-sign">
      <p className="ui-flabel" id={id}>
        {label}
      </p>
      <canvas
        aria-labelledby={id}
        className="ji-pad"
        onPointerDown={(event) => {
          const context = event.currentTarget.getContext("2d");
          drawing.current = true;
          setEmpty(false);
          try {
            event.currentTarget.setPointerCapture(event.pointerId);
          } catch {
            // Some browsers (and the test screen) cannot capture the pointer; drawing still works.
          }
          if (context === null) {
            setDrawn(true);
            return;
          }
          const { x, y } = point(event);
          context.beginPath();
          context.moveTo(x, y);
        }}
        onPointerMove={(event) => {
          if (!drawing.current) return;
          const context = event.currentTarget.getContext("2d");
          setDrawn(true);
          if (context === null) return;
          const { x, y } = point(event);
          context.lineTo(x, y);
          context.stroke();
        }}
        onPointerUp={() => {
          drawing.current = false;
        }}
        onPointerLeave={() => {
          drawing.current = false;
        }}
        ref={canvas}
        role="img"
      />
      {empty && (
        <p className="ui-error" role="alert">
          {jt(language, "sign_empty")}
        </p>
      )}
      <div className="ui-actions">
        <button
          className="ui-btn"
          disabled={busy}
          onClick={clear}
          type="button"
        >
          {jt(language, "sign_clear")}
        </button>
        <button
          className="ui-btn primary"
          disabled={busy}
          onClick={() => {
            const pad = canvas.current;
            if (pad === null || !drawn) {
              setEmpty(true);
              return;
            }
            pad.toBlob((picture) => {
              if (picture !== null) onSave(picture);
            }, "image/png");
          }}
          type="button"
        >
          {jt(language, "sign_save")}
        </button>
      </div>
    </div>
  );
}
