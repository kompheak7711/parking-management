// V1-060 B6: the report charts (DESIGN.md "Charts"), in plain HTML and CSS: columns by month,
// stacked when there is more than one series, and a bar list with each value written at the end
// of its bar. Series take the chart colours in their fixed order (reports.css). Every column has a
// tooltip on hover and keyboard focus, only the highest column is labelled, and the columns have
// a hidden table for screen readers.

export interface ChartColumn {
  /** Under the column, such as "Oct 26". */
  label: string;
  /** In the tooltip and the hidden table, such as "October 2026". */
  tip: string;
  /** One value per series. A part below zero (a reversal) is not drawn; the tooltip has it. */
  values: readonly number[];
}

/** A round top for the axis: 1, 2, 2.5, 5 or 10 times a power of ten. */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = value / power;
  const nice =
    step <= 1 ? 1 : step <= 2 ? 2 : step <= 2.5 ? 2.5 : step <= 5 ? 5 : 10;
  return nice * power;
}

function percent(part: number, whole: number): string {
  const share = whole > 0 ? Math.min(100, (part / whole) * 100) : 0;
  return `${share.toFixed(2)}%`;
}

function sumOf(values: readonly number[], drawnOnly: boolean): number {
  return values.reduce(
    (sum, value) => sum + (drawnOnly ? Math.max(0, value) : value),
    0,
  );
}

export function StackedBars({
  title,
  head,
  series,
  columns,
  format,
  axisFormat = format,
  totalLabel,
  color = 1,
}: {
  title: string;
  /** The first column of the hidden table: "Month" or "Day". */
  head: string;
  series: readonly string[];
  columns: readonly ChartColumn[];
  format: (value: number) => string;
  axisFormat?: (value: number) => string;
  /** "Total", for the tooltip of a stacked column. */
  totalLabel: string;
  /** The chart colour of the first series, 1 to 8. */
  color?: number;
}) {
  if (columns.length === 0) return null;
  const multi = series.length > 1;
  const drawn = columns.map((column) => sumOf(column.values, true));
  const highest = Math.max(...drawn);
  const top = niceMax(highest);
  const best = highest > 0 ? drawn.indexOf(highest) : -1;
  // A long run of months shows about eight labels under the columns.
  const step = columns.length > 14 ? Math.ceil(columns.length / 8) : 1;
  const grid = {
    gridTemplateColumns: `repeat(${String(columns.length)}, minmax(0, 1fr))`,
  };
  return (
    <figure className="rp-chart">
      <figcaption className="rp-chart-t">{title}</figcaption>
      {multi && (
        <ul className="rp-legend">
          {series.map((name, index) => (
            <li key={name}>
              <i
                aria-hidden="true"
                className={`rp-s${String(color + index)}`}
              />
              {name}
            </li>
          ))}
        </ul>
      )}
      <div className="rp-vc">
        <div aria-hidden="true" className="rp-vc-y">
          <span style={{ bottom: "100%" }}>{axisFormat(top)}</span>
          <span style={{ bottom: "50%" }}>{axisFormat(top / 2)}</span>
          <span style={{ bottom: "0%" }}>{axisFormat(0)}</span>
        </div>
        <div className="rp-vc-plot">
          <i aria-hidden="true" className="rp-vc-g" style={{ bottom: "50%" }} />
          <i
            aria-hidden="true"
            className="rp-vc-g"
            style={{ bottom: "100%" }}
          />
          <div className="rp-vc-cols" style={grid}>
            {columns.map((column, index) => {
              const height = drawn[index] ?? 0;
              const parts = series.flatMap((name, part) => {
                const value = column.values[part] ?? 0;
                if (value === 0) return [];
                return [multi ? `${name}: ${format(value)}` : format(value)];
              });
              const lines = [
                column.tip,
                ...(parts.length === 0 ? [format(0)] : parts),
                ...(multi && parts.length > 0
                  ? [`${totalLabel}: ${format(sumOf(column.values, false))}`]
                  : []),
              ];
              return (
                <button
                  aria-label={lines.join(", ")}
                  className="rp-vc-col"
                  data-tip={lines.join("\n")}
                  key={`${String(index)}:${column.tip}`}
                  type="button"
                >
                  {index === best && (
                    <span
                      className="rp-vc-v"
                      style={{ bottom: percent(height, top) }}
                    >
                      {/* V1-060 B7: the figure is the column's total, a reversal taken off,
                          as in the table and the tooltip; the height shows what is drawn. */}
                      {format(sumOf(column.values, false))}
                    </span>
                  )}
                  <span
                    className="rp-vc-bar"
                    style={{ height: percent(height, top) }}
                  >
                    {series.map((name, part) => {
                      const value = Math.max(0, column.values[part] ?? 0);
                      return value === 0 ? null : (
                        <span
                          className={`rp-vc-seg rp-s${String(color + part)}`}
                          key={name}
                          style={{ height: percent(value, height) }}
                        />
                      );
                    })}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <div aria-hidden="true" className="rp-vc-x" style={grid}>
        {columns.map((column, index) => (
          <span key={`${String(index)}:${column.tip}`}>
            {index % step === 0 ? column.label : ""}
          </span>
        ))}
      </div>
      <table className="ui-sr">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">{head}</th>
            {series.map((name) => (
              <th key={name} scope="col">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {columns.map((column, index) => (
            <tr key={`${String(index)}:${column.tip}`}>
              <th scope="row">{column.tip}</th>
              {series.map((name, part) => (
                <td key={name}>{format(column.values[part] ?? 0)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

export interface BarRow {
  label: string;
  value: number;
}

/** One series: a labelled bar for each row with its value written at the end. */
export function BarList({
  title,
  rows,
  format,
  color = 1,
}: {
  title: string;
  rows: readonly BarRow[];
  format: (value: number) => string;
  color?: number;
}) {
  if (rows.length === 0) return null;
  const top = Math.max(1, ...rows.map((row) => row.value));
  return (
    <figure className="rp-chart">
      <figcaption className="rp-chart-t">{title}</figcaption>
      <ul className="rp-hc">
        {rows.map((row, index) => (
          <li key={`${String(index)}:${row.label}`}>
            <span className="rp-hc-l">{row.label}</span>
            <span aria-hidden="true" className="rp-hc-b">
              <i
                className={`rp-s${String(color)}`}
                style={{ width: percent(Math.max(0, row.value), top) }}
              />
            </span>
            <span className="rp-hc-v ui-num">{format(row.value)}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
