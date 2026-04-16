import { useState, useEffect, useCallback } from 'react'
import StatusBar from './components/StatusBar'
import ParticipantChart from './components/ParticipantChart'
import OITable from './components/OITable'
import StrikeChart from './components/StrikeChart'

const SYMBOLS = ['NIFTY', 'BANKNIFTY']

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
    fetchAll()
    const interval = setInterval(fetchAll, 30000)
    return () => clearInterval(interval)
  }, [fetchAll])

  const currentOi = oiData[activeTab]

  return (
    <div className="max-w-[1400px] mx-auto px-4 py-4">
      <h1 className="text-2xl font-bold mb-4">📊 OI Tracker</h1>

      <StatusBar status={status} onRefresh={fetchAll} />

      <ParticipantChart data={participants} />

      <div className="border-t border-gray-700 my-4" />

      {/* Tabs */}
      <div className="flex gap-1 mb-4">
        {SYMBOLS.map(s => (
          <button
            key={s}
            onClick={() => { setActiveTab(s); setSelectedStrike(null) }}
            className={`px-6 py-2 rounded-t-lg font-semibold text-sm transition-colors ${
              activeTab === s
                ? 'bg-[var(--bg-secondary)] text-[var(--gold)] border-b-2 border-[var(--gold)]'
                : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {currentOi && currentOi.rows.length > 0 ? (
        <>
          {/* Summary metrics */}
          <div className="grid grid-cols-3 gap-4 mb-4">
            <Metric label="Total CE OI" value={currentOi.totals.total_ce.toLocaleString()} />
            <Metric label="Total PE OI" value={currentOi.totals.total_pe.toLocaleString()} />
            <Metric label="PCR" value={pcrLabel(currentOi.totals.pcr)} />
          </div>

          {/* Info bar */}
          <div className="flex flex-wrap items-center gap-4 mb-3 text-sm">
            <span className="bg-[var(--gold)] text-black px-3 py-1 rounded-xl font-bold text-sm">
              SPOT: ₹{Number(currentOi.spot).toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </span>
            <span className="text-[var(--text-muted)]">Last update: {currentOi.last_update}</span>
            {currentOi.old_date && (
              <span className="text-[var(--text-muted)]">Old = close of {currentOi.old_date}</span>
            )}
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
          <br />Run <code className="bg-gray-800 px-2 py-1 rounded text-sm">python3 collector.py --live</code>
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

function Metric({ label, value }) {
  return (
    <div className="bg-[var(--bg-secondary)] rounded-lg p-3 text-center">
      <div className="text-xs text-[var(--text-muted)] mb-1">{label}</div>
      <div className="text-lg font-bold">{value}</div>
    </div>
  )
}

function pcrLabel(pcr) {
  if (pcr > 1.2) return `${pcr.toFixed(2)} 🟢 Bullish`
  if (pcr < 0.8) return `${pcr.toFixed(2)} 🔴 Bearish`
  return `${pcr.toFixed(2)} ⚪ Neutral`
}
