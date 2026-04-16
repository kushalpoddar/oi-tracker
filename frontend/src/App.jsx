import { useState, useEffect, useCallback } from 'react'
import StatusBar from './components/StatusBar'
import ParticipantChart from './components/ParticipantChart'
import OITable from './components/OITable'
import StrikeChart from './components/StrikeChart'

const SYMBOLS = ['NIFTY', 'BANKNIFTY']

function fmtDate(d) {
  if (!d) return ''
  const parts = d.split('-')
  if (parts.length === 3) return `${parts[2]}-${parts[1]}-${parts[0]}`
  return d
}

function fmtTime(ts) {
  if (!ts) return ''
  const timePart = ts.split(' ').pop()?.split('.')[0]
  return timePart || ts
}

export default function App() {
  const [activeTab, setActiveTab] = useState('NIFTY')
  const [status, setStatus] = useState(null)
  const [participants, setParticipants] = useState(null)
  const [oiData, setOiData] = useState({})
  const [selectedStrike, setSelectedStrike] = useState(null)

  const fetchAll = useCallback(async () => {
    try {
      const [statusRes, partRes, ...oiResults] = await Promise.all([
        fetch('/api/status'),
        fetch('/api/participants'),
        ...SYMBOLS.map(s => fetch(`/api/oi/${s}`)),
      ])
      setStatus(await statusRes.json())
      setParticipants(await partRes.json())
      const newOi = {}
      for (let i = 0; i < SYMBOLS.length; i++) {
        newOi[SYMBOLS[i]] = await oiResults[i].json()
      }
      setOiData(newOi)
    } catch (e) {
      console.error('Fetch error:', e)
    }
  }, [])

  useEffect(() => {
    let active = true
    const run = async () => { if (active) await fetchAll() }
    run()
    const interval = setInterval(fetchAll, 30000)
    return () => { active = false; clearInterval(interval) }
  }, [fetchAll])

  const currentOi = oiData[activeTab]

  return (
    <div className="max-w-[1400px] mx-auto px-4 py-4">
      <StatusBar status={status} onRefresh={fetchAll} />

      <ParticipantChart data={participants} />

      {/* Tabs */}
      <div className="flex gap-0 mt-5 border-b border-gray-700">
        {SYMBOLS.map(s => (
          <button
            key={s}
            onClick={() => { setActiveTab(s); setSelectedStrike(null) }}
            className={`px-5 py-2.5 font-semibold text-sm transition-all relative cursor-pointer ${
              activeTab === s
                ? 'text-[var(--gold)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            {s}
            {activeTab === s && (
              <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-[var(--gold)] rounded-t" />
            )}
          </button>
        ))}
      </div>

      {currentOi && currentOi.rows.length > 0 ? (
        <>
          {/* Spot + Metrics row */}
          <div className="flex flex-wrap items-stretch gap-3 mt-4 mb-4">
            {/* Spot price */}
            <div className="bg-gradient-to-r from-[var(--gold)]/15 to-transparent border border-[var(--gold)]/30 rounded-lg px-4 py-2.5 flex items-center gap-2">
              <span className="text-[var(--gold)] text-xs font-semibold uppercase tracking-wide">Spot</span>
              <span className="text-[var(--gold)] text-lg font-bold tabular-nums">
                ₹{Number(currentOi.spot).toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            </div>

            {/* CE OI */}
            <div className="bg-[var(--bg-secondary)] border border-gray-700/50 rounded-lg px-4 py-2.5 flex items-center gap-2">
              <span className="text-[var(--ce-color)] text-xs font-semibold uppercase tracking-wide">CE OI</span>
              <span className="text-[var(--text-primary)] text-sm font-bold tabular-nums">{currentOi.totals.total_ce.toLocaleString()}</span>
            </div>

            {/* PE OI */}
            <div className="bg-[var(--bg-secondary)] border border-gray-700/50 rounded-lg px-4 py-2.5 flex items-center gap-2">
              <span className="text-[var(--pe-color)] text-xs font-semibold uppercase tracking-wide">PE OI</span>
              <span className="text-[var(--text-primary)] text-sm font-bold tabular-nums">{currentOi.totals.total_pe.toLocaleString()}</span>
            </div>

            {/* PCR */}
            <div className={`border rounded-lg px-4 py-2.5 flex items-center gap-2 ${pcrStyle(currentOi.totals.pcr)}`}>
              <span className="text-xs font-semibold uppercase tracking-wide">PCR</span>
              <span className="text-sm font-bold tabular-nums">{currentOi.totals.pcr.toFixed(2)}</span>
            </div>

            {/* Last update + old date */}
            <div className="flex items-center gap-3 ml-auto text-[11px] text-[var(--text-muted)]">
              {currentOi.last_update && <span>Updated {fmtTime(currentOi.last_update)}</span>}
              {currentOi.old_date && <span>Prev close: {fmtDate(currentOi.old_date)}</span>}
            </div>
          </div>

          <OITable
            symbol={activeTab}
            rows={currentOi.rows}
            onStrikeClick={(strike) => setSelectedStrike(strike)}
            selectedStrike={selectedStrike}
          />
        </>
      ) : currentOi ? (
        <div className="text-center py-12 text-[var(--text-muted)]">
          No live data for <b>{activeTab}</b> yet today.
          <br />Run <code className="bg-gray-800 px-2 py-1 rounded text-sm mt-2 inline-block">python3 collector.py --live</code>
        </div>
      ) : (
        <div className="text-center py-12 text-[var(--text-muted)]">Loading...</div>
      )}

      {selectedStrike && (
        <StrikeChart
          symbol={activeTab}
          strike={selectedStrike}
          onClose={() => setSelectedStrike(null)}
        />
      )}
    </div>
  )
}

function pcrStyle(pcr) {
  if (pcr > 1.2) return 'bg-[var(--green)]/10 border-[var(--green)]/30 text-[var(--green)]'
  if (pcr < 0.8) return 'bg-[var(--red)]/10 border-[var(--red)]/30 text-[var(--red)]'
  return 'bg-[var(--bg-secondary)] border-gray-700/50 text-[var(--text-primary)]'
}
