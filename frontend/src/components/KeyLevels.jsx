export default function KeyLevels({ levels, spot }) {
  if (!levels) return null

  const { resistance = [], support = [], max_pain } = levels
  if (!resistance.length && !support.length && !max_pain) return null

  const fmtOI = (v) => {
    if (v >= 1_00_00_000) return (v / 1_00_00_000).toFixed(1) + 'Cr'
    if (v >= 1_00_000) return (v / 1_00_000).toFixed(1) + 'L'
    if (v >= 1000) return (v / 1000).toFixed(0) + 'K'
    return v.toLocaleString('en-IN')
  }

  const maxOI = Math.max(
    ...resistance.map(r => r.oi),
    ...support.map(s => s.oi),
    1,
  )

  return (
    <div className="mt-3 mb-3 rounded-lg border border-gray-700/50 overflow-hidden"
      style={{ background: 'var(--bg-secondary)' }}
    >
      <div className="px-4 py-2 border-b border-gray-700/50 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Key Levels (OI-based)
        </span>
        {max_pain && (
          <span className="text-[11px] text-[var(--text-muted)]">
            Max Pain:{' '}
            <span className="font-bold text-[var(--gold)]">{max_pain.toLocaleString('en-IN')}</span>
          </span>
        )}
      </div>

      <div className="flex">
        {/* Resistance (left) */}
        <div className="flex-1 px-3 py-2 border-r border-gray-700/30">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--red)] opacity-70 mb-1.5">
            Resistance
          </div>
          <div className="flex flex-col gap-1">
            {[...resistance].reverse().map((r, i) => {
              const tag = `R${resistance.length - i}`
              const barW = Math.max((r.oi / maxOI) * 100, 8)
              return (
                <div key={r.strike} className="flex items-center gap-2">
                  <span className="text-[10px] font-bold text-[var(--red)] opacity-60 w-5 shrink-0">{tag}</span>
                  <span className="text-xs font-semibold tabular-nums w-14 text-right text-[var(--text-primary)]">
                    {r.strike.toLocaleString('en-IN')}
                  </span>
                  <div className="flex-1 h-3.5 rounded-sm overflow-hidden" style={{ background: 'rgba(239,83,80,0.1)' }}>
                    <div
                      className="h-full rounded-sm flex items-center justify-end px-1"
                      style={{ width: `${barW}%`, background: 'rgba(239,83,80,0.35)' }}
                    >
                      <span className="text-[9px] font-semibold text-[var(--red)]">{fmtOI(r.oi)}</span>
                    </div>
                  </div>
                  <ChgBadge val={r.chg_oi} />
                </div>
              )
            })}
          </div>
        </div>

        {/* Spot center */}
        <div className="shrink-0 flex flex-col items-center justify-center px-4 py-2"
          style={{ background: 'rgba(255,215,0,0.06)' }}
        >
          <span className="text-[9px] uppercase tracking-wider text-[var(--gold)] opacity-60 font-semibold">Spot</span>
          <span className="text-sm font-bold text-[var(--gold)] tabular-nums">
            {Number(spot).toLocaleString('en-IN')}
          </span>
        </div>

        {/* Support (right) */}
        <div className="flex-1 px-3 py-2 border-l border-gray-700/30">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--green)] opacity-70 mb-1.5">
            Support
          </div>
          <div className="flex flex-col gap-1">
            {support.map((s, i) => {
              const tag = `S${i + 1}`
              const barW = Math.max((s.oi / maxOI) * 100, 8)
              return (
                <div key={s.strike} className="flex items-center gap-2">
                  <span className="text-[10px] font-bold text-[var(--green)] opacity-60 w-5 shrink-0">{tag}</span>
                  <span className="text-xs font-semibold tabular-nums w-14 text-right text-[var(--text-primary)]">
                    {s.strike.toLocaleString('en-IN')}
                  </span>
                  <div className="flex-1 h-3.5 rounded-sm overflow-hidden" style={{ background: 'rgba(102,187,106,0.1)' }}>
                    <div
                      className="h-full rounded-sm flex items-center justify-end px-1"
                      style={{ width: `${barW}%`, background: 'rgba(102,187,106,0.35)' }}
                    >
                      <span className="text-[9px] font-semibold text-[var(--green)]">{fmtOI(s.oi)}</span>
                    </div>
                  </div>
                  <ChgBadge val={s.chg_oi} />
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

function ChgBadge({ val }) {
  if (!val) return <span className="w-10" />
  const color = val > 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'
  const arrow = val > 0 ? '▲' : '▼'
  const fmt = Math.abs(val) >= 1000
    ? (Math.abs(val) / 1000).toFixed(0) + 'K'
    : Math.abs(val).toLocaleString('en-IN')
  return (
    <span className={`text-[9px] font-semibold ${color} w-10 text-right shrink-0`}>
      {arrow}{fmt}
    </span>
  )
}
