import { useState } from 'react'

export default function StatusBar({ status, onRefresh }) {
  const [spinning, setSpinning] = useState(false)

  const handleRefresh = async () => {
    setSpinning(true)
    await onRefresh()
    setTimeout(() => setSpinning(false), 600)
  }

  return (
    <div className="flex items-center justify-between mb-5">
      {/* Left — branding */}
      <div className="flex items-center gap-3">
        <div className="text-2xl font-extrabold tracking-tight">
          <span className="text-[var(--gold)]">OI</span>
          <span className="text-[var(--text-primary)]"> Tracker</span>
        </div>
        {status && (
          <div className="hidden sm:flex items-center gap-1.5 ml-2 px-2.5 py-1 rounded-full bg-[var(--bg-secondary)] border border-gray-700 text-[11px] text-[var(--text-muted)]">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--green)] animate-pulse" />
            Live
          </div>
        )}
      </div>

      {/* Right — time, snaps, refresh */}
      <div className="flex items-center gap-3">
        {status && (
          <>
            <div className="text-right hidden sm:block">
              <div className="text-sm font-semibold text-[var(--text-primary)] tabular-nums">{status.time} <span className="text-[var(--text-muted)] font-normal text-xs">IST</span></div>
              <div className="text-[11px] text-[var(--text-muted)]">{status.snap_count} snapshots</div>
            </div>
            <div className="sm:hidden text-xs text-[var(--text-muted)] tabular-nums">{status.time}</div>
          </>
        )}
        <button
          onClick={handleRefresh}
          className="w-9 h-9 flex items-center justify-center rounded-lg bg-[var(--bg-secondary)] border border-gray-700 hover:border-[var(--blue)] hover:bg-[var(--bg-hover)] transition-all cursor-pointer"
          title="Refresh data"
        >
          <svg
            className={`w-4 h-4 text-[var(--blue)] ${spinning ? 'animate-spin' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>
    </div>
  )
}
