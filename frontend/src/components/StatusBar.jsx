import { useState } from 'react'

export default function StatusBar({ onRefresh }) {
  const [spinning, setSpinning] = useState(false)

  const handleRefresh = async () => {
    setSpinning(true)
    await onRefresh()
    setTimeout(() => setSpinning(false), 600)
  }

  return (
    <div className="mb-5">
      {/* Row 1 on mobile: logo only. Desktop: logo + title + refresh */}
      <div className="flex items-center gap-3">
        <img src="/logo.svg" alt="spotprice.in" className="h-8 sm:h-9 shrink-0" />
        <div className="hidden sm:block text-center flex-1">
          <h1 className="text-2xl font-bold">
            <span className="text-[var(--gold)]">Live</span>{' '}
            <span className="text-[var(--text-primary)]">Price Action Tracker for</span>{' '}
            <span className="text-[var(--green)]">Options Traders</span>
          </h1>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5 tracking-wide">beta edition (trial underway)</p>
        </div>
        <button
          onClick={handleRefresh}
          className="hidden sm:flex w-8 h-8 items-center justify-center rounded-lg bg-[var(--bg-secondary)] border border-gray-700 hover:border-[var(--blue)] hover:bg-[var(--bg-hover)] transition-all cursor-pointer shrink-0"
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

      {/* Row 2 on mobile: title + refresh */}
      <div className="flex sm:hidden items-center gap-2 mt-2">
        <div className="flex-1">
          <h1 className="text-base font-bold">
            <span className="text-[var(--gold)]">Live</span>{' '}
            <span className="text-[var(--text-primary)]">Price Action Tracker for</span>{' '}
            <span className="text-[var(--green)]">Options Traders</span>
          </h1>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 tracking-wide">beta edition (trial underway)</p>
        </div>
        <button
          onClick={handleRefresh}
          className="w-8 h-8 flex items-center justify-center rounded-lg bg-[var(--bg-secondary)] border border-gray-700 hover:border-[var(--blue)] hover:bg-[var(--bg-hover)] transition-all cursor-pointer shrink-0"
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
