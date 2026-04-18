import { useState, useEffect, useCallback, useRef } from 'react'
import StatusBar from './components/StatusBar'
import ParticipantChart from './components/ParticipantChart'
import KeyLevels from './components/KeyLevels'
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

function dteLabel(dte) {
  if (dte === null || dte === undefined) return ''
  if (dte === 0) return 'Expiry today'
  if (dte === 1) return '1 day left'
  return `${dte} days left`
}

function dteColor(dte) {
  if (dte === null || dte === undefined) return ''
  if (dte <= 1) return 'text-[var(--red)]'
  if (dte <= 3) return 'text-[var(--gold)]'
  return 'text-[var(--text-muted)]'
}

export default function App() {
  const [activeTab, setActiveTab] = useState('NIFTY')
  const [status, setStatus] = useState(null)
  const [participants, setParticipants] = useState(null)
  const [oiData, setOiData] = useState({})
  const [selectedStrike, setSelectedStrike] = useState(null)
  const [expiries, setExpiries] = useState({})
  const [selectedExpiry, setSelectedExpiry] = useState({})
  const selectedExpiryRef = useRef(selectedExpiry)
  useEffect(() => { selectedExpiryRef.current = selectedExpiry }, [selectedExpiry])

  const fetchExpiries = useCallback(async () => {
    const newExpiries = {}
    await Promise.all(SYMBOLS.map(async (s) => {
      try {
        const res = await fetch(`/api/expiries/${s}`)
        const data = await res.json()
        newExpiries[s] = data.expiries || []
      } catch { newExpiries[s] = [] }
    }))
    setExpiries(newExpiries)
    setSelectedExpiry(prev => {
      const next = { ...prev }
      for (const s of SYMBOLS) {
        if (!next[s] && newExpiries[s]?.length) next[s] = newExpiries[s][0].label
      }
      return next
    })
    return newExpiries
  }, [])

  const fetchOi = useCallback(async () => {
    const curExpiry = selectedExpiryRef.current
    try {
      const [statusRes, partRes, ...oiResults] = await Promise.all([
        fetch('/api/status'),
        fetch('/api/participants'),
        ...SYMBOLS.map(s => {
          const exp = curExpiry[s]
          const qs = exp ? `?expiry=${encodeURIComponent(exp)}` : ''
          return fetch(`/api/oi/${s}${qs}`)
        }),
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
    const init = async () => {
      if (!active) return
      await fetchExpiries()
      if (active) await fetchOi()
    }
    init()
    const interval = setInterval(fetchOi, 30000)
    return () => { active = false; clearInterval(interval) }
  }, [fetchExpiries, fetchOi])

  useEffect(() => {
    fetchOi()
  }, [selectedExpiry]) // eslint-disable-line react-hooks/exhaustive-deps

  const currentOi = oiData[activeTab]
  const currentExpiries = expiries[activeTab] || []
  const activeExpiry = selectedExpiry[activeTab] || ''

  const handleExpiryChange = (expLabel) => {
    setSelectedExpiry(prev => ({ ...prev, [activeTab]: expLabel }))
    setSelectedStrike(null)
  }

  return (
    <div className="px-2 sm:px-4 py-3">
      <StatusBar status={status} onRefresh={() => { fetchExpiries(); fetchOi() }} />

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

      {/* Expiry selector */}
      {currentExpiries.length > 0 && (
        <div className="flex items-center gap-2 mt-4 flex-wrap">
          <span className="text-[11px] text-[var(--text-muted)] uppercase tracking-wide font-semibold">Expiry</span>
          <div className="flex gap-1.5 flex-wrap">
            {currentExpiries.map(exp => (
              <button
                key={exp.label}
                onClick={() => handleExpiryChange(exp.label)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer border ${
                  activeExpiry === exp.label
                    ? 'bg-[var(--gold)] text-black border-[var(--gold)]'
                    : 'bg-[var(--bg-secondary)] text-[var(--text-muted)] border-gray-700 hover:border-[var(--gold)]/50 hover:text-[var(--text-primary)]'
                }`}
              >
                {exp.label}
                <span className={`ml-1.5 text-[10px] ${activeExpiry === exp.label ? 'text-black/60' : dteColor(exp.dte)}`}>
                  {exp.dte === 0 ? '(today)' : `(${exp.dte}d)`}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {currentOi && currentOi.rows.length > 0 ? (
        <>
          {/* Spot price + expiry info */}
          <div className="flex items-center justify-between mt-3 mb-2"
            style={{ background: 'rgba(255,215,0,0.08)', border: '1px solid rgba(255,215,0,0.25)', borderRadius: 8, padding: '10px 16px' }}
          >
            <div className="flex items-center gap-2">
              <span className="text-[var(--gold)] text-xs font-semibold uppercase tracking-wide">Spot</span>
              <span className="text-[var(--gold)] text-xl font-bold tabular-nums">
                ₹{Number(currentOi.spot).toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            </div>
            <div className="flex items-center gap-3 text-[11px] text-[var(--text-muted)]">
              {currentOi.expiry && (
                <span className="flex items-center gap-1.5">
                  <span>Exp: {currentOi.expiry}</span>
                  {currentOi.dte !== null && currentOi.dte !== undefined && (
                    <span className={`font-bold ${dteColor(currentOi.dte)}`}>
                      ({dteLabel(currentOi.dte)})
                    </span>
                  )}
                </span>
              )}
              {currentOi.last_update && <span>Updated {fmtTime(currentOi.last_update)}</span>}
              {currentOi.old_date && <span>Prev close: {fmtDate(currentOi.old_date)}</span>}
            </div>
          </div>

          <KeyLevels levels={currentOi.levels} spot={currentOi.spot} />

          {/* CE OI, PE OI, PCR */}
          <div className="flex gap-3 mb-4">
            <div className="flex-1 bg-[var(--bg-secondary)] border border-gray-700/50 rounded-lg px-4 py-2 flex items-center justify-center gap-2">
              <span className="text-[var(--ce-color)] text-xs font-semibold uppercase tracking-wide">CE OI</span>
              <span className="text-[var(--text-primary)] text-sm font-bold tabular-nums">{currentOi.totals.total_ce.toLocaleString()}</span>
            </div>
            <div className="flex-1 bg-[var(--bg-secondary)] border border-gray-700/50 rounded-lg px-4 py-2 flex items-center justify-center gap-2">
              <span className="text-[var(--pe-color)] text-xs font-semibold uppercase tracking-wide">PE OI</span>
              <span className="text-[var(--text-primary)] text-sm font-bold tabular-nums">{currentOi.totals.total_pe.toLocaleString()}</span>
            </div>
            <div className="flex-1 rounded-lg px-4 py-2 flex items-center justify-center gap-2" style={pcrStyle(currentOi.totals.pcr)}>
              <span className="text-xs font-semibold uppercase tracking-wide">PCR</span>
              <span className="text-sm font-bold tabular-nums">{currentOi.totals.pcr.toFixed(2)}</span>
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
          expiry={activeExpiry}
          onClose={() => setSelectedStrike(null)}
        />
      )}
    </div>
  )
}

function pcrStyle(pcr) {
  if (pcr > 1.2) return { background: 'rgba(102,187,106,0.12)', border: '1px solid rgba(102,187,106,0.35)', color: 'var(--green)' }
  if (pcr < 0.8) return { background: 'rgba(239,83,80,0.12)', border: '1px solid rgba(239,83,80,0.35)', color: 'var(--red)' }
  return { background: 'var(--bg-secondary)', border: '1px solid rgba(107,114,128,0.5)', color: 'var(--text-primary)' }
}
