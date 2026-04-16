import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, Cell, LabelList } from 'recharts'

function fmtDate(d) {
  if (!d) return ''
  const parts = d.split('-')
  if (parts.length === 3) return `${parts[2]}-${parts[1]}-${parts[0]}`
  return d
}

function formatContracts(val) {
  const abs = Math.abs(val)
  if (abs >= 100000) return `${(val / 100000).toFixed(1)}L`
  if (abs >= 1000) return `${Math.round(val / 1000)}K`
  return val.toLocaleString()
}

export default function ParticipantChart({ data }) {
  if (!data || !data.available) {
    return (
      <div className="text-center text-sm text-[var(--text-muted)] py-4">
        No participant OI data yet. Available after 5:30 PM on trading days.
      </div>
    )
  }

  const chartData = data.data.map(p => ({
    name: p.name,
    Long: p.long,
    Short: p.short,
    net: p.net,
  }))

  return (
    <div className="mb-4">
      <div className="text-center text-sm text-[var(--text-muted)] mb-2">
        📅 {fmtDate(data.trade_date)} &nbsp;&nbsp; <b>Gross Open Interest — Index Options</b>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} barCategoryGap="10%">
          <XAxis dataKey="name" tick={{ fill: '#e0e0e0', fontSize: 12 }} />
          <YAxis tick={{ fill: '#aaa', fontSize: 11 }} tickFormatter={v => formatContracts(v)} />
          <Tooltip
            contentStyle={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 8 }}
            labelStyle={{ color: '#e0e0e0' }}
            formatter={(v) => v.toLocaleString()}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="Long" fill="#66BB6A" radius={[3, 3, 0, 0]}>
            <LabelList dataKey="Long" position="top" formatter={formatContracts} style={{ fill: '#66BB6A', fontSize: 11, fontWeight: 600 }} />
          </Bar>
          <Bar dataKey="Short" fill="#ef5350" radius={[3, 3, 0, 0]}>
            <LabelList dataKey="Short" position="top" formatter={formatContracts} style={{ fill: '#ef5350', fontSize: 11, fontWeight: 600 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
