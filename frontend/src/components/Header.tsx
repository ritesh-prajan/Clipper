import React from 'react'
import { HardDrive, DollarSign, Activity } from 'lucide-react'

interface Props {
  title: string
  subtitle?: string
  diskUsedGb?: number
  diskCapGb?: number
  spendUsd?: number
  spendCapUsd?: number
  activeStreamsCount?: number
}

export const Header: React.FC<Props> = ({
  title,
  subtitle,
  diskUsedGb = 0,
  diskCapGb = 20,
  spendUsd = 0,
  spendCapUsd = 10,
  activeStreamsCount = 0,
}) => {
  const diskPct = Math.min(100, Math.round((diskUsedGb / (diskCapGb || 1)) * 100))
  const spendPct = Math.min(100, Math.round((spendUsd / (spendCapUsd || 1)) * 100))

  return (
    <header className="h-16 px-8 bg-slate-900/60 border-b border-slate-800 backdrop-blur-md flex items-center justify-between shrink-0">
      <div>
        <h2 className="text-lg font-bold text-slate-100">{title}</h2>
        {subtitle && <p className="text-xs text-slate-400">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-6 text-xs text-slate-300">
        {/* Active Streams */}
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            {activeStreamsCount > 0 ? (
              <>
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </>
            ) : (
              <span className="relative inline-flex rounded-full h-2 w-2 bg-slate-500"></span>
            )}
          </span>
          <span className="text-slate-400">
            Streams: <strong className="text-slate-200">{activeStreamsCount} active</strong>
          </span>
        </div>

        {/* Disk Usage */}
        <div className="flex items-center gap-2">
          <HardDrive className="w-4 h-4 text-slate-400" />
          <div className="flex flex-col">
            <span className="text-[11px] text-slate-400">
              Disk: <strong className="text-slate-200">{diskUsedGb.toFixed(1)} GB</strong> / {diskCapGb} GB
            </span>
            <div className="w-20 bg-slate-800 h-1.5 rounded-full overflow-hidden mt-0.5">
              <div
                className={`h-full rounded-full ${diskPct > 85 ? 'bg-rose-500' : 'bg-indigo-500'}`}
                style={{ width: `${diskPct}%` }}
              />
            </div>
          </div>
        </div>

        {/* Gemini Spend */}
        <div className="flex items-center gap-2">
          <DollarSign className="w-4 h-4 text-slate-400" />
          <div className="flex flex-col">
            <span className="text-[11px] text-slate-400">
              Spend: <strong className="text-slate-200">${spendUsd.toFixed(2)}</strong> / ${spendCapUsd.toFixed(2)}
            </span>
            <div className="w-20 bg-slate-800 h-1.5 rounded-full overflow-hidden mt-0.5">
              <div
                className={`h-full rounded-full ${spendPct >= 100 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                style={{ width: `${spendPct}%` }}
              />
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
