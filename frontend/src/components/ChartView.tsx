import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis,
} from "recharts";
import type { ChartSpec } from "../lib/types";

const PALETTE = ["#5a7f60", "#b5674d", "#c9a44c", "#7a9cb8", "#8c6f9e"];
const PALETTE_DARK = ["#8fb596", "#d78f75", "#d9b868", "#93b3cc", "#b39cc4"];

function isDark() {
  return document.documentElement.dataset.theme === "dark";
}

/** Renders a study-guide chart spec. Bar charts use point labels as categories. */
export function ChartView({ spec, height = 300 }: { spec: ChartSpec; height?: number }) {
  const colors = isDark() ? PALETTE_DARK : PALETTE;
  const series = spec.series.filter((s) => s.points.length);
  if (!series.length) return null;
  const axisProps = { stroke: "var(--muted)", fontSize: 12, tickLine: false };
  const grid = <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />;
  const tooltip = <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, color: "var(--text)" }} />;
  const legend = series.length > 1 ? <Legend /> : null;
  const xLabel = spec.x_label ? { value: spec.x_label, position: "insideBottom" as const, offset: -4, fill: "var(--muted)", fontSize: 12 } : undefined;
  const yLabel = spec.y_label ? { value: spec.y_label, angle: -90, position: "insideLeft" as const, fill: "var(--muted)", fontSize: 12 } : undefined;
  const margin = { top: 10, right: 20, bottom: 18, left: 10 };

  let chart;
  if (spec.chart_type === "bar") {
    const labels = series[0].points.map((p, i) => p.label || String(p.x ?? i));
    const rows = labels.map((label, i) => {
      const row: Record<string, string | number> = { label };
      for (const s of series) row[s.name] = s.points[i]?.y ?? 0;
      return row;
    });
    chart = (
      <BarChart data={rows} margin={margin}>
        {grid}<XAxis dataKey="label" {...axisProps} label={xLabel} /><YAxis {...axisProps} label={yLabel} />{tooltip}{legend}
        {series.map((s, i) => <Bar key={s.name} dataKey={s.name} fill={colors[i % colors.length]} radius={[6, 6, 0, 0]} />)}
      </BarChart>
    );
  } else if (spec.chart_type === "scatter") {
    chart = (
      <ScatterChart margin={margin}>
        {grid}<XAxis type="number" dataKey="x" {...axisProps} label={xLabel} /><YAxis type="number" dataKey="y" {...axisProps} label={yLabel} />{tooltip}{legend}
        {series.map((s, i) => <Scatter key={s.name} name={s.name} data={s.points} fill={colors[i % colors.length]} />)}
      </ScatterChart>
    );
  } else {
    // line / area: merge series on x
    const xs = Array.from(new Set(series.flatMap((s) => s.points.map((p) => p.x)))).sort((a, b) => a - b);
    const rows = xs.map((x) => {
      const row: Record<string, number> = { x };
      for (const s of series) {
        const p = s.points.find((pt) => pt.x === x);
        if (p) row[s.name] = p.y;
      }
      return row;
    });
    const Chart = spec.chart_type === "area" ? AreaChart : LineChart;
    chart = (
      <Chart data={rows} margin={margin}>
        {grid}<XAxis type="number" dataKey="x" domain={["dataMin", "dataMax"]} {...axisProps} label={xLabel} /><YAxis {...axisProps} label={yLabel} />{tooltip}{legend}
        {series.map((s, i) =>
          spec.chart_type === "area"
            ? <Area key={s.name} type="monotone" dataKey={s.name} stroke={colors[i % colors.length]} fill={colors[i % colors.length]} fillOpacity={0.18} connectNulls isAnimationActive={false} />
            : <Line key={s.name} type="monotone" dataKey={s.name} stroke={colors[i % colors.length]} strokeWidth={2.2} dot={false} connectNulls isAnimationActive={false} />,
        )}
      </Chart>
    );
  }
  return (
    <div>
      {spec.title && <div style={{ fontWeight: 650, textAlign: "center", marginBottom: 6 }}>{spec.title}</div>}
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer>{chart}</ResponsiveContainer>
      </div>
    </div>
  );
}
