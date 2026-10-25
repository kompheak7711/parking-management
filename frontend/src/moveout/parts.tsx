// V1-058 R3 Move-out: the parts of the Move-out page that its steps share.

import type { ReactNode } from "react";

import { Icon } from "../shell/icons";
import { Chip, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import { mt } from "./text";

export function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="ui-kv">
      {rows.map(([term, value], index) => (
        <div key={`${String(index)}:${term}`} style={{ display: "contents" }}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export type Mark = "done" | "now" | "todo" | "skip";

export function Step({
  language,
  number,
  mark,
  title,
  children,
  actions,
}: {
  language: Language;
  number: number;
  mark: Mark;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  const tone: Tone =
    mark === "done" ? "ok" : mark === "now" ? "info" : "neutral";
  return (
    <li className={`ui-mstep s-${mark}`}>
      <span aria-hidden="true" className={`ui-mark ${mark}`}>
        {mark === "done" ? (
          <Icon name="check" small />
        ) : mark === "skip" ? (
          "–"
        ) : (
          ""
        )}
      </span>
      <div className="ui-mbody">
        <div className="ui-mhead">
          <h3>
            {number}. {title}
          </h3>
          <Chip tone={tone}>{mt(language, mark)}</Chip>
        </div>
        {children}
        {actions !== undefined && <div className="ui-actions">{actions}</div>}
      </div>
    </li>
  );
}
