import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ChartRecommendation, QueryResult } from '../api/client'
import { humanizeColumn } from '../lib/format'
import { CHART_COLORS as COLORS } from './LiveChart'
import './ResultChart.css'

const TOOLTIP_STYLE = {
  background: 'var(--cl-surface-container-lowest)',
  border: '1px solid var(--cl-border)',
  borderRadius: 'var(--cl-radius)',
  boxShadow: 'var(--cl-shadow-level-2)',
  fontFamily: 'var(--cl-font-body)',
  fontSize: 12.5,
  color: 'var(--cl-on-surface)',
}

type Props = {
  result: QueryResult
  chart?: ChartRecommendation | null
  chartType?: string
  height?: number
}

function toNumber(value: unknown): number {
  if (typeof value === 'number') return value
  const n = Number(String(value ?? '').replace(/,/g, ''))
  return Number.isFinite(n) ? n : 0
}

/** Parse a label as a date, or null when it is an ordinary category. */
function labelDate(value: unknown): number | null {
  const text = String(value ?? '').trim()
  // Require a date-ish shape so plain numeric categories are not misread.
  if (!/^\d{4}[-/]\d{1,2}([-/]\d{1,2})?/.test(text)) return null
  const ms = Date.parse(text)
  return Number.isNaN(ms) ? null : ms
}

export function ResultChart({ result, chart, chartType, height = 220 }: Props) {
  const type = chartType || chart?.type || 'table'
  if (type === 'table' || !result.rows.length) return null

  const labelKey = chart?.label_key || result.columns[0]
  // A store/product answer needs both columns in the label, or the axis reads
  // "Lagos, Lagos, Lagos" with no way to tell the bars apart.
  const labelKeys = chart?.label_keys?.length ? chart.label_keys : [labelKey]
  const valueKeys =
    chart?.value_keys?.length
      ? chart.value_keys
      : result.columns.filter((c) => !labelKeys.includes(c)).slice(0, 2)

  if (!labelKey || valueKeys.length === 0) return null

  const rows = result.rows.slice(0, 40)
  const labelOf = (row: Record<string, unknown>) =>
    labelKeys
      .map((key) => String(row[key] ?? '').trim())
      .filter(Boolean)
      .join(' · ')

  // A line chart implies time order. The SQL may be sorted by a measure
  // instead (e.g. ORDER BY revenue DESC), which would draw a meaningless
  // zig-zag, so re-sort chronologically when the labels are dates.
  const ordered =
    type === 'line' && rows.every((row) => labelDate(row[labelKey]) !== null)
      ? [...rows].sort((a, b) => labelDate(a[labelKey])! - labelDate(b[labelKey])!)
      : rows

  const data = ordered.map((row) => {
    const item: Record<string, string | number> = { [labelKey]: labelOf(row) }
    for (const key of valueKeys) {
      item[key] = toNumber(row[key])
    }
    return item
  })

  if (type === 'hbar') {
    // One row per label: readable at twenty categories, where a vertical axis
    // drops most of the names. The card grows rather than squeezing them.
    const rowHeight = 26
    const chartHeight = Math.max(height, data.length * rowHeight + 48)
    return (
      <div className="result-chart" style={{ height: chartHeight }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--cl-chart-grid)" />
            <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--cl-chart-axis)' }}
              tickLine={false} axisLine={false} />
            <YAxis
              type="category"
              dataKey={labelKey}
              tick={{ fontSize: 11, fill: 'var(--cl-chart-axis)' }}
              tickLine={false}
              axisLine={false}
              width={168}
              interval={0}
              tickFormatter={(v: unknown) => {
                const text = String(v ?? '')
                return text.length > 26 ? `${text.slice(0, 25)}…` : text
              }}
            />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--cl-accent-quiet)' }} />
            {valueKeys.length > 1 && (
              <Legend
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 12, fontFamily: 'var(--cl-font-body)', paddingTop: 4 }}
              />
            )}
            {valueKeys.map((key, i) => (
              <Bar
                key={key}
                dataKey={key}
                name={humanizeColumn(key)}
                fill={COLORS[i % COLORS.length]}
                radius={[0, 2, 2, 0]}
                maxBarSize={valueKeys.length > 1 ? 9 : 16}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    )
  }

  if (type === 'pie') {
    const key = valueKeys[0]
    const pieData = data.map((d) => ({
      name: String(d[labelKey]),
      value: toNumber(d[key]),
    }))
    return (
      <div className="result-chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={pieData} dataKey="value" nameKey="name" outerRadius="75%" label>
              {pieData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--cl-accent-quiet)' }} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    )
  }

  if (type === 'line') {
    return (
      <div className="result-chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--cl-chart-grid)" />
            <XAxis dataKey={labelKey} tick={{ fontSize: 11, fill: 'var(--cl-chart-axis)' }}
              tickLine={false}
              axisLine={false} />
            <YAxis tick={{ fontSize: 11, fill: 'var(--cl-chart-axis)' }}
              tickLine={false}
              axisLine={false} />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--cl-accent-quiet)' }} />
            {valueKeys.length > 1 && (
              <Legend
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 12, fontFamily: 'var(--cl-font-body)', paddingTop: 4 }}
              />
            )}
            {valueKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                name={humanizeColumn(key)}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={2}
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    )
  }

  return (
    <div className="result-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--cl-chart-grid)" />
          <XAxis dataKey={labelKey} tick={{ fontSize: 11, fill: 'var(--cl-chart-axis)' }}
              tickLine={false}
              axisLine={false} />
          <YAxis tick={{ fontSize: 11, fill: 'var(--cl-chart-axis)' }}
              tickLine={false}
              axisLine={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--cl-accent-quiet)' }} />
          {valueKeys.length > 1 && (
            <Legend
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12, fontFamily: 'var(--cl-font-body)', paddingTop: 4 }}
            />
          )}
          {valueKeys.map((key, i) => (
            <Bar
              key={key}
              dataKey={key}
              name={humanizeColumn(key)}
              fill={COLORS[i % COLORS.length]}
              radius={[2, 2, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
