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

export default function OITable({ symbol, rows, onStrikeClick, selectedStrike }) {
  return (
    <div className="overflow-x-auto -mx-4 px-4" style={{ WebkitOverflowScrolling: 'touch' }}>
      <table className="w-full min-w-[800px] border-collapse font-mono text-[13px] whitespace-nowrap">
        <thead>
          <tr>
            <th colSpan={4} className="text-center text-sm font-bold py-1.5 border-b-2 border-gray-600 text-[var(--ce-color)]">
              CALL (CE)
            </th>
            <th className="text-center text-sm font-bold py-1.5 border-b-2 border-gray-600 text-[var(--gold)] bg-[#1a1a2e]">⬍</th>
            <th colSpan={4} className="text-center text-sm font-bold py-1.5 border-b-2 border-gray-600 text-[var(--pe-color)]">
              PUT (PE)
            </th>
          </tr>
          <tr className="text-xs font-semibold text-[var(--text-muted)] border-b border-gray-700">
            {['Vol', 'Chg OI', 'OI', 'Live'].map(h => <th key={`ce-${h}`} className="py-1 px-2 text-center">{h}</th>)}
            <th className="py-1 px-2 text-center text-[var(--gold)] bg-[#1a1a2e]">STRIKE</th>
            {['Live', 'OI', 'Chg OI', 'Vol'].map(h => <th key={`pe-${h}`} className="py-1 px-2 text-center">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const isSelected = selectedStrike === row.strike
            return (
              <tr
                key={row.strike}
                className={`border-b border-gray-800/50 ${row.is_atm ? 'bg-yellow-900/20' : ''} ${isSelected ? 'bg-blue-900/30' : ''}`}
              >
                <td className="text-center px-2 py-2.5 text-[var(--ce-color)] opacity-50">{row.ce_volume.toLocaleString()}</td>
                <td className={`text-center px-2 py-2.5 ${chgColor(row.ce_chg_oi)}`}>{fmtChg(row.ce_chg_oi)}</td>
                <td className="text-center px-2 py-2.5 text-[var(--ce-color)] opacity-50">{row.ce_old.toLocaleString()}</td>
                <td className="text-center px-2 py-2.5">
                  <button
                    onClick={() => onStrikeClick(row.strike)}
                    className={`${liveColor(row.ce_pct)} hover:text-white hover:underline cursor-pointer bg-transparent border-none font-mono text-[13px] p-0`}
                  >
                    {row.ce_live.toLocaleString()}{pctTag(row.ce_pct)}
                  </button>
                </td>
                <td className={`text-center px-2 py-2.5 font-semibold bg-[#1a1a2e] ${row.is_atm ? 'text-[var(--gold)] font-extrabold text-[15px]' : 'text-[var(--text-primary)]'}`}>
                  {row.strike.toLocaleString()}
                </td>
                <td className="text-center px-2 py-2.5">
                  <button
                    onClick={() => onStrikeClick(row.strike)}
                    className={`${liveColor(row.pe_pct)} hover:text-white hover:underline cursor-pointer bg-transparent border-none font-mono text-[13px] p-0`}
                  >
                    {row.pe_live.toLocaleString()}{pctTag(row.pe_pct)}
                  </button>
                </td>
                <td className="text-center px-2 py-2.5 text-[var(--pe-color)] opacity-50">{row.pe_old.toLocaleString()}</td>
                <td className={`text-center px-2 py-2.5 ${chgColor(row.pe_chg_oi)}`}>{fmtChg(row.pe_chg_oi)}</td>
                <td className="text-center px-2 py-2.5 text-[var(--pe-color)] opacity-50">{row.pe_volume.toLocaleString()}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
