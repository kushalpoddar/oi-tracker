import { useState, useEffect, useRef } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts'

export default function StrikeChart({ symbol, strike, onClose }) {
  const [data, setData] = useState(null)
  const backdropRef = useRef(null)

  useEffect(() => {
    fetch(`/api/chart/${symbol}/${strike}`)
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => setData([]))
  }, [symbol, strike])

  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  const handleBackdropClick = (e) => {
    if (e.target === backdropRef.current) onClose()
  }

  const chartData = data?.length
    ? data.map(d => ({
        time: d.timestamp.split(' ').pop()?.split('.')[0]?.slice(0, 5) || d.timestamp,
        'Call OI': d.ce_oi,
        'Put OI': d.pe_oi,
      }))
    : []

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    >
      <div className="bg-[var(--bg-secondary)] rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl border border-gray-700">
        <div className="flex justify-between items-center px-5 py-4 border-b border-gray-700">
          <h3 className="font-bold text-lg">📈 {symbol} — {strike.toLocaleString()}</h3>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-white cursor-pointer bg-transparent border-none text-2xl leading-none px-2"
          >
            ✕
          </button>
        </div>

        <div className="p-5">
          {data === null ? (
            <div className="text-center py-12 text-[var(--text-muted)]">Loading chart...</div>
          ) : data.length === 0 ? (
            <div className="text-center py-12 text-[var(--text-muted)]">No intraday data for this strike yet.</div>
          ) : (
            <ResponsiveContainer width="100%" height={350}>
              <AreaChart data={chartData}>
                <XAxis dataKey="time" tick={{ fill: '#aaa', fontSize: 11 }} />
                <YAxis tick={{ fill: '#aaa', fontSize: 11 }} tickFormatter={v => (v / 1000).toFixed(0) + 'K'} />
                <Tooltip
                  contentStyle={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 8 }}
                  labelStyle={{ color: '#e0e0e0' }}
                  formatter={(v) => v.toLocaleString()}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="Call OI" stroke="#ef5350" fill="#ef5350" fillOpacity={0.1} strokeWidth={2} />
                <Area type="monotone" dataKey="Put OI" stroke="#66bb6a" fill="#66bb6a" fillOpacity={0.1} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  )
}
