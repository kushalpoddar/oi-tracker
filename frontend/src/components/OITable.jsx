import { useEffect, useRef, useCallback } from 'react'

function pctTag(pct) {
  if (pct === 0) return null
  const arrow = pct > 0 ? '▲' : '▼'
  const cls = pct > 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'
  return <span className={`${cls} text-[11px] ml-1`}>{arrow}{Math.abs(pct).toFixed(1)}%</span>
}

function liveColor(pct) {
  if (pct > 0) return 'text-[var(--green)]'
  if (pct < 0) return 'text-[var(--red)]'
  return 'text-[var(--blue)]'
}

function chgColor(val) {
  if (val > 0) return 'text-[var(--green)]'
  if (val < 0) return 'text-[var(--red)]'
  return 'text-gray-600'
}

function fmtChg(val) {
  return val > 0 ? `+${val.toLocaleString()}` : val.toLocaleString()
}

export default function OITable({ rows, onStrikeClick, selectedStrike }) {
  const leftRef = useRef(null)
  const rightRef = useRef(null)
  const ceTableRef = useRef(null)
  const strikeTableRef = useRef(null)
  const peTableRef = useRef(null)

  const hasAnyPct = rows.some(r => r.ce_pct !== 0 || r.pe_pct !== 0)

  const syncHeights = useCallback(() => {
    const tables = [ceTableRef.current, strikeTableRef.current, peTableRef.current]
    if (tables.some(t => !t)) return

    const rowSets = tables.map(t => Array.from(t.querySelectorAll('tr')))
    const rowCount = Math.min(...rowSets.map(r => r.length))

    // Reset heights first
    rowSets.forEach(set => set.forEach(tr => { tr.style.height = '' }))

    for (let i = 0; i < rowCount; i++) {
      const maxH = Math.max(...rowSets.map(set => set[i].getBoundingClientRect().height))
      rowSets.forEach(set => { set[i].style.height = `${maxH}px` })
    }
  }, [])

  useEffect(() => {
    syncHeights()
    if (leftRef.current) leftRef.current.scrollLeft = leftRef.current.scrollWidth
    if (rightRef.current) rightRef.current.scrollLeft = 0
  }, [rows, syncHeights])

  return (
    <div className="flex font-mono text-[13px]">
      {/* CE side */}
      <div ref={leftRef} className="flex-1 overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
        <table ref={ceTableRef} className="w-full border-collapse whitespace-nowrap">
          <thead>
            <tr className="bg-[#2a1520]">
              <th colSpan={4} className="text-center text-sm font-bold py-2 text-[var(--ce-color)] tracking-wider uppercase">
                CALL (CE)
              </th>
            </tr>
            <tr className="bg-[#1e1215] border-b border-[var(--ce-color)]/30">
              {['Vol', 'Chg OI', 'OI', 'Live'].map(h => <th key={h} className="py-1.5 px-1 text-center text-[11px] font-semibold text-[var(--ce-color)] opacity-70 uppercase tracking-wide">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr
                key={row.strike}
                className={`border-b border-gray-800/50 ${row.is_atm ? 'bg-yellow-900/20' : ''} ${selectedStrike === row.strike ? 'bg-blue-900/30' : ''}`}
              >
                <td className="text-center px-1 py-1.5 text-[var(--ce-color)] opacity-50">{row.ce_volume.toLocaleString()}</td>
                <td className={`text-center px-1 py-1.5 ${chgColor(row.ce_chg_oi)}`}>{fmtChg(row.ce_chg_oi)}</td>
                <td className="text-center px-1 py-1.5 text-[var(--ce-color)] opacity-50">{row.ce_old.toLocaleString()}</td>
                <td className="text-center px-1 py-1.5">
                  <button
                    onClick={() => onStrikeClick(row.strike)}
                    className={`${liveColor(row.ce_pct)} hover:text-white hover:underline cursor-pointer bg-transparent border-none font-mono text-[13px] p-0`}
                  >
                    {row.ce_live.toLocaleString()}
                    {hasAnyPct && <div className="text-[11px]">{pctTag(row.ce_pct) || '\u00A0'}</div>}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Strike center */}
      <div className="shrink-0" style={{ background: '#ffd700' }}>
        <table ref={strikeTableRef} className="border-collapse whitespace-nowrap">
          <thead>
            <tr style={{ background: '#ffd700' }}>
              <th className="text-center text-sm font-bold py-2 text-black px-3 tracking-wider uppercase">Index</th>
            </tr>
            <tr className="border-b border-yellow-700" style={{ background: '#e6c200' }}>
              <th className="py-1.5 px-3 text-center text-[11px] font-semibold text-black uppercase tracking-wide">STRIKE</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr
                key={row.strike}
                className="border-b border-yellow-600/40"
                style={{ background: row.is_atm ? '#ff8c00' : '#ffd700' }}
              >
                <td className={`text-center px-3 py-1.5 font-semibold text-black ${row.is_atm ? 'font-extrabold text-[15px]' : ''}`}>
                  {row.strike.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* PE side */}
      <div ref={rightRef} className="flex-1 overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
        <table ref={peTableRef} className="w-full border-collapse whitespace-nowrap">
          <thead>
            <tr className="bg-[#152a1a]">
              <th colSpan={4} className="text-center text-sm font-bold py-2 text-[var(--pe-color)] tracking-wider uppercase">
                PUT (PE)
              </th>
            </tr>
            <tr className="bg-[#121e15] border-b border-[var(--pe-color)]/30">
              {['Live', 'OI', 'Chg OI', 'Vol'].map(h => <th key={h} className="py-1.5 px-1 text-center text-[11px] font-semibold text-[var(--pe-color)] opacity-70 uppercase tracking-wide">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr
                key={row.strike}
                className={`border-b border-gray-800/50 ${row.is_atm ? 'bg-yellow-900/20' : ''} ${selectedStrike === row.strike ? 'bg-blue-900/30' : ''}`}
              >
                <td className="text-center px-1 py-1.5">
                  <button
                    onClick={() => onStrikeClick(row.strike)}
                    className={`${liveColor(row.pe_pct)} hover:text-white hover:underline cursor-pointer bg-transparent border-none font-mono text-[13px] p-0`}
                  >
                    {row.pe_live.toLocaleString()}
                    {hasAnyPct && <div className="text-[11px]">{pctTag(row.pe_pct) || '\u00A0'}</div>}
                  </button>
                </td>
                <td className="text-center px-1 py-1.5 text-[var(--pe-color)] opacity-50">{row.pe_old.toLocaleString()}</td>
                <td className={`text-center px-1 py-1.5 ${chgColor(row.pe_chg_oi)}`}>{fmtChg(row.pe_chg_oi)}</td>
                <td className="text-center px-1 py-1.5 text-[var(--pe-color)] opacity-50">{row.pe_volume.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
