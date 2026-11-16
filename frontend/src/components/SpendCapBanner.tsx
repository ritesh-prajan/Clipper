import React from 'react'
import { AlertTriangle, Settings as SettingsIcon } from 'lucide-react'

interface Props {
  spend: number
  cap: number
  onNavigateSettings?: () => void
}

export const SpendCapBanner: React.FC<Props> = ({ spend, cap, onNavigateSettings }) => {
  return (
    <div className="bg-amber-500/10 border-b border-amber-500/30 px-6 py-3 flex items-center justify-between text-amber-200">
      <div className="flex items-center gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 animate-pulse" />
        <span className="text-sm font-medium">
          <strong className="text-amber-300 font-semibold">Gemini Spend Cap Reached:</strong> ${spend.toFixed(2)} spent of ${cap.toFixed(2)} cap.
          Chunk submissions to OpenShorts are paused to protect your budget.
        </span>
      </div>
      {onNavigateSettings && (
        <button
          onClick={onNavigateSettings}
          className="flex items-center gap-1.5 px-3 py-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded text-xs font-semibold transition"
        >
          <SettingsIcon className="w-3.5 h-3.5" />
          Adjust Cap
        </button>
      )}
    </div>
  )
}
