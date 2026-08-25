import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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

export function ResultChart({ result, chart, chartType, height = 220 }: Props) {
  const type = chartType || chart?.type || 'table'
  if (type === 'table' || !result.rows.length) return null

  const labelKey = chart?.label_key || result.columns[0]
  const valueKeys =
    chart?.value_keys?.length
      ? chart.value_keys
      : result.columns.filter((c) => c !== labelKey).slice(0, 2)

  if (!labelKey || valueKeys.length === 0) return null

  const data = result.rows.slice(0, 40).map((row) => {
    const item: Record<string, string | number> = {
      [labelKey]: String(row[labelKey] ?? ''),
    }
    for (const key of valueKeys) {
      item[key] = toNumber(row[key])
    }
    return item
  })

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
            {valueKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
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
          {valueKeys.map((key, i) => (
            <Bar key={key} dataKey={key} fill={COLORS[i % COLORS.length]} radius={[2, 2, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
