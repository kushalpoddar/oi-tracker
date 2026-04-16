import { useState, useEffect } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

export default function StrikeChart({ symbol, strike, onClose }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    fetch(`/api/chart/${symbol}/${strike}`)
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => setData([]))
  }, [symbol, strike])

  if (data === null) {
    return <div className="text-center py-8 text-[var(--text-muted)]">Loading chart...</div>
  }

  if (data.length === 0) {
    return (
      <div className="bg-[var(--bg-secondary)] rounded-lg p-4 mt-4">
        <div className="flex justify-between items-center mb-2">
          <h3 className="font-bold">📈 OI Chart — {symbol} {strike.toLocaleString()}</h3>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white cursor-pointer bg-transparent border-none text-lg">✕</button>
        </div>
        <p className="text-sm text-[var(--text-muted)]">No intraday data for this strike yet.</p>
      </div>
    )
  }

  const chartData = data.map(d => ({
    time: d.timestamp.split(' ').pop()?.split('.')[0]?.slice(0, 5) || d.timestamp,
    ce_oi: d.ce_oi,
    pe_oi: d.pe_oi,
  }))

  return (
    <div className="bg-[var(--bg-secondary)] rounded-lg p-4 mt-4" id="oi-chart">
      <div className="flex justify-between items-center mb-4">
        <h3 className="font-bold text-lg">📈 OI Chart — {symbol} {strike.toLocaleString()}</h3>
        <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white cursor-pointer bg-transparent border-none text-xl px-2">✕</button>
      </div>

      {/* CE OI Chart */}
      <div className="mb-4">
        <div className="text-sm font-semibold text-[var(--ce-color)] mb-1">CALL OI</div>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={chartData}>
            <XAxis dataKey="time" tick={{ fill: '#aaa', fontSize: 11 }} />
            <YAxis tick={{ fill: '#aaa', fontSize: 11 }} tickFormatter={v => (v / 1000).toFixed(0) + 'K'} />
            <Tooltip
              contentStyle={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 8 }}
              labelStyle={{ color: '#e0e0e0' }}
              formatter={(v) => v.toLocaleString()}
            />
            <Area type="monotone" dataKey="ce_oi" stroke="#ef5350" fill="#ef5350" fillOpacity={0.15} strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* PE OI Chart */}
      <div>
        <div className="text-sm font-semibold text-[var(--pe-color)] mb-1">PUT OI</div>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={chartData}>
            <XAxis dataKey="time" tick={{ fill: '#aaa', fontSize: 11 }} />
            <YAxis tick={{ fill: '#aaa', fontSize: 11 }} tickFormatter={v => (v / 1000).toFixed(0) + 'K'} />
            <Tooltip
              contentStyle={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 8 }}
              labelStyle={{ color: '#e0e0e0' }}
              formatter={(v) => v.toLocaleString()}
            />
            <Area type="monotone" dataKey="pe_oi" stroke="#66bb6a" fill="#66bb6a" fillOpacity={0.15} strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
