import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, LabelList } from 'recharts'

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
    'CE Long': p.ce_long,
    'CE Short': p.ce_short,
    'PE Long': p.pe_long,
    'PE Short': p.pe_short,
  }))

  return (
    <div className="mb-4">
      <div className="text-center text-sm text-[var(--text-muted)] mb-2">
        📅 {fmtDate(data.trade_date)} &nbsp;&nbsp; <b>Participant-wise Open Interest — Index Options</b>
      </div>

      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={chartData} layout="vertical" barCategoryGap="10%" margin={{ left: 10, right: 40 }}>
          <YAxis dataKey="name" type="category" tick={{ fill: '#e0e0e0', fontSize: 12 }} width={50} />
          <XAxis type="number" tick={{ fill: '#aaa', fontSize: 11 }} tickFormatter={v => formatContracts(v)} />
          <Tooltip
            contentStyle={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 8 }}
            labelStyle={{ color: '#e0e0e0' }}
            formatter={(v) => v.toLocaleString()}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="CE Long" fill="#ef9a9a" radius={[0, 3, 3, 0]}>
            <LabelList dataKey="CE Long" position="right" formatter={formatContracts} style={{ fill: '#ef9a9a', fontSize: 10, fontWeight: 600 }} />
          </Bar>
          <Bar dataKey="CE Short" fill="#c62828" radius={[0, 3, 3, 0]}>
            <LabelList dataKey="CE Short" position="right" formatter={formatContracts} style={{ fill: '#c62828', fontSize: 10, fontWeight: 600 }} />
          </Bar>
          <Bar dataKey="PE Long" fill="#a5d6a7" radius={[0, 3, 3, 0]}>
            <LabelList dataKey="PE Long" position="right" formatter={formatContracts} style={{ fill: '#a5d6a7', fontSize: 10, fontWeight: 600 }} />
          </Bar>
          <Bar dataKey="PE Short" fill="#2e7d32" radius={[0, 3, 3, 0]}>
            <LabelList dataKey="PE Short" position="right" formatter={formatContracts} style={{ fill: '#2e7d32', fontSize: 10, fontWeight: 600 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
