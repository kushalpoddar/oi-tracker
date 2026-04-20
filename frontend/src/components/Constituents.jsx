import { useState, useEffect, useCallback } from 'react'

const COLS = [
  { key: 'rank', label: '#', align: 'center', sortable: false },
  { key: 'symbol', label: 'Stock', align: 'left', sortable: true },
  { key: 'industry', label: 'Sector', align: 'left', sortable: true },
  { key: 'ltp', label: 'LTP', align: 'right', sortable: true },
  { key: 'pct_change', label: 'Chg %', align: 'right', sortable: true },
  { key: 'weight', label: 'Weight %', align: 'right', sortable: true },
  { key: 'volume', label: 'Volume', align: 'right', sortable: true },
]

function fmt(n) {
  return Number(n).toLocaleString('en-IN')
}

function fmtDec(n, d = 2) {
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })
}

function chgColor(v) {
  if (v > 0) return 'var(--green)'
  if (v < 0) return 'var(--red)'
  return 'var(--text-muted)'
}

function rowBg(pctChange) {
  if (pctChange > 0) return 'rgba(102,187,106,0.06)'
  if (pctChange < 0) return 'rgba(239,83,80,0.06)'
  return 'transparent'
}

export default function Constituents({ symbol }) {
  const [data, setData] = useState(null)
  const [sortKey, setSortKey] = useState('weight')
  const [sortAsc, setSortAsc] = useState(false)
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/constituents/${symbol}`)
      const json = await res.json()
      if (json.available) setData(json)
    } catch (e) {
      console.error('Constituents fetch error:', e)
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    setData(null)
    fetchData()
    const interval = setInterval(fetchData, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(key === 'symbol' || key === 'industry')
    }
  }

  const stocks = data?.stocks || []

  const sorted = [...stocks].sort((a, b) => {
    let av = a[sortKey], bv = b[sortKey]
    if (typeof av === 'string') av = av.toLowerCase()
    if (typeof bv === 'string') bv = bv.toLowerCase()
    if (av < bv) return sortAsc ? -1 : 1
    if (av > bv) return sortAsc ? 1 : -1
    return 0
  })

  const maxWeight = Math.max(...stocks.map(s => s.weight), 1)

  return (
    <div className="mt-3">
      {/* Index summary bar */}
      {data && (
        <div className="flex items-center justify-between flex-wrap gap-3 mb-4 px-4 py-3 rounded-lg"
          style={{
            background: data.index_pct_change >= 0 ? 'rgba(102,187,106,0.08)' : 'rgba(239,83,80,0.08)',
            border: `1px solid ${data.index_pct_change >= 0 ? 'rgba(102,187,106,0.3)' : 'rgba(239,83,80,0.3)'}`,
          }}
        >
          <div className="flex items-center gap-3">
            <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">{data.index}</span>
            <span className="text-xl font-bold tabular-nums" style={{ color: chgColor(data.index_pct_change) }}>
              {fmtDec(data.index_value)}
            </span>
            <span className="text-sm font-bold" style={{ color: chgColor(data.index_pct_change) }}>
              {data.index_change >= 0 ? '+' : ''}{fmtDec(data.index_change)}
              {' '}({data.index_pct_change >= 0 ? '+' : ''}{data.index_pct_change}%)
            </span>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <span className="text-[var(--green)] font-semibold">▲ {data.advances}</span>
            <span className="text-[var(--red)] font-semibold">▼ {data.declines}</span>
            <span className="text-[var(--text-muted)] font-semibold">— {data.unchanged}</span>
            {data.last_update && (
              <span className="text-[var(--text-muted)]">Updated: {data.last_update}</span>
            )}
          </div>
        </div>
      )}

      {/* Table */}
      {loading && !data ? (
        <div className="text-center py-12 text-[var(--text-muted)]">Loading...</div>
      ) : !data ? (
        <div className="text-center py-12 text-[var(--text-muted)]">No data available</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-700/50">
          <table className="w-full text-[13px]" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-secondary)' }}>
                {COLS.map(col => (
                  <th
                    key={col.key}
                    onClick={() => col.sortable && handleSort(col.key)}
                    className={`px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)] ${
                      col.sortable ? 'cursor-pointer hover:text-[var(--gold)]' : ''
                    }`}
                    style={{ textAlign: col.align, whiteSpace: 'nowrap' }}
                  >
                    {col.label}
                    {sortKey === col.key && (
                      <span className="ml-1 text-[var(--gold)]">{sortAsc ? '▲' : '▼'}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((st, i) => (
                <tr
                  key={st.symbol}
                  style={{ background: rowBg(st.pct_change), borderBottom: '1px solid rgba(107,114,128,0.2)' }}
                  className="hover:brightness-125 transition-all"
                >
                  <td className="px-3 py-2 text-center text-[var(--text-muted)] text-[11px]">{i + 1}</td>
                  <td className="px-3 py-2">
                    <div className="font-bold text-[var(--text-primary)]">{st.symbol}</div>
                    <div className="text-[10px] text-[var(--text-muted)] truncate max-w-[180px]">{st.company}</div>
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)] text-[11px] max-w-[140px] truncate">{st.industry}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold text-[var(--text-primary)]">
                    ₹{fmtDec(st.ltp)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-bold" style={{ color: chgColor(st.pct_change) }}>
                    <div>{st.pct_change >= 0 ? '+' : ''}{st.pct_change}%</div>
                    <div className="text-[10px] font-normal" style={{ color: chgColor(st.change) }}>
                      {st.change >= 0 ? '+' : ''}₹{fmtDec(st.change)}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.2)' }}>
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${(st.weight / maxWeight) * 100}%`,
                            background: 'var(--gold)',
                            opacity: 0.7,
                          }}
                        />
                      </div>
                      <span className="tabular-nums font-semibold text-[var(--gold)] min-w-[40px]">{st.weight}%</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[var(--text-muted)]">
                    {fmt(st.volume)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
