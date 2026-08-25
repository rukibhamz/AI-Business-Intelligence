import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { OverviewChart } from '../api/client'
import { formatExact, formatValue } from '../lib/format'
import './LiveChart.css'

export const CHART_COLORS = [
  'var(--cl-chart-1)',
  'var(--cl-chart-2)',
  'var(--cl-chart-3)',
  'var(--cl-chart-4)',
  'var(--cl-chart-5)',
  'var(--cl-chart-6)',
  'var(--cl-chart-7)',
  'var(--cl-chart-8)',
]

const axisTick = {
  fontSize: 11,
  fontFamily: 'var(--cl-font-body)',
  fill: 'var(--cl-chart-axis)',
}

const tooltipStyle = {
  background: 'var(--cl-surface-container-lowest)',
  border: '1px solid var(--cl-border)',
  borderRadius: 'var(--cl-radius)',
  boxShadow: 'var(--cl-shadow-level-2)',
  fontFamily: 'var(--cl-font-body)',
  fontSize: 12.5,
  color: 'var(--cl-on-surface)',
  padding: '8px 10px',
}

/** Trim long category names so axis labels stay readable. */
function shortLabel(value: unknown): string {
  const text = String(value ?? '')
  return text.length > 14 ? `${text.slice(0, 13)}…` : text
}

export function LiveChart({ chart, height = 260 }: { chart: OverviewChart; height?: number }) {
  const { data, label_key: labelKey, value_keys: valueKeys, format } = chart

  const tooltipFormatter = (value: unknown, name: unknown) => [
    formatExact(value as number, format),
    String(name),
  ]

  if (chart.type === 'hbar') {
    return (
      <div className="live-chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid horizontal={false} stroke="var(--cl-chart-grid)" strokeDasharray="3 3" />
            <XAxis
              type="number"
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => formatValue(v as number, format)}
            />
            <YAxis
              type="category"
              dataKey={labelKey}
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              width={96}
              tickFormatter={shortLabel}
            />
            <Tooltip
              contentStyle={tooltipStyle}
              cursor={{ fill: 'var(--cl-accent-quiet)' }}
              formatter={tooltipFormatter}
            />
            <Bar dataKey={valueKeys[0]} radius={[0, 4, 4, 0]} maxBarSize={22}>
              {data.map((_, i) => (
                <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    )
  }

  if (chart.type === 'line') {
    return (
      <div className="live-chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 6, right: 12, bottom: 4, left: 4 }}>
            <defs>
              {valueKeys.map((key, i) => (
                <linearGradient key={key} id={`grad-${chart.id}-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor={CHART_COLORS[i % CHART_COLORS.length]}
                    stopOpacity={0.28}
                  />
                  <stop
                    offset="100%"
                    stopColor={CHART_COLORS[i % CHART_COLORS.length]}
                    stopOpacity={0.02}
                  />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid vertical={false} stroke="var(--cl-chart-grid)" strokeDasharray="3 3" />
            <XAxis dataKey={labelKey} tick={axisTick} tickLine={false} axisLine={false} />
            <YAxis
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              width={56}
              tickFormatter={(v) => formatValue(v as number, format)}
            />
            <Tooltip
              contentStyle={tooltipStyle}
              cursor={{ stroke: 'var(--cl-outline-variant)', strokeWidth: 1 }}
              formatter={tooltipFormatter}
            />
            {valueKeys.length > 1 && (
              <Legend
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 12, fontFamily: 'var(--cl-font-body)', paddingTop: 6 }}
              />
            )}
            {valueKeys.map((key, i) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                stroke={CHART_COLORS[i % CHART_COLORS.length]}
                strokeWidth={2}
                fill={`url(#grad-${chart.id}-${i})`}
                dot={false}
                activeDot={{ r: 4 }}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    )
  }

  return (
    <div className="live-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 6, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--cl-chart-grid)" strokeDasharray="3 3" />
          <XAxis
            dataKey={labelKey}
            tick={axisTick}
            tickLine={false}
            axisLine={false}
            tickFormatter={shortLabel}
            interval={0}
            angle={data.length > 6 ? -25 : 0}
            textAnchor={data.length > 6 ? 'end' : 'middle'}
            height={data.length > 6 ? 52 : 30}
          />
          <YAxis
            tick={axisTick}
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(v) => formatValue(v as number, format)}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            cursor={{ fill: 'var(--cl-accent-quiet)' }}
            formatter={tooltipFormatter}
          />
          {valueKeys.length > 1 && (
            <Legend
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12, fontFamily: 'var(--cl-font-body)', paddingTop: 6 }}
            />
          )}
          {valueKeys.map((key, i) => (
            <Bar
              key={key}
              dataKey={key}
              radius={[4, 4, 0, 0]}
              maxBarSize={44}
              fill={CHART_COLORS[i % CHART_COLORS.length]}
            >
              {valueKeys.length === 1 &&
                data.map((_, index) => (
                  <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
