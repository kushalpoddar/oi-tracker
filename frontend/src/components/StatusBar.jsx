export default function StatusBar({ status, onRefresh }) {
  if (!status) return null

  return (
    <div className="flex flex-wrap items-center gap-6 mb-4 text-sm">
      <span>🕐 <b>{status.time}</b> IST</span>
      <span>📸 <b>{status.snap_count}</b> snapshots today</span>
      <button
        onClick={onRefresh}
        className="px-3 py-1 bg-[var(--bg-secondary)] rounded hover:bg-[var(--bg-hover)] transition-colors text-[var(--blue)] cursor-pointer"
      >
        🔄 Refresh
      </button>
    </div>
  )
}
