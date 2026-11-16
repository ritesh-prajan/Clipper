import React from 'react'
import {
  Radio,
  Scissors,
  CheckCircle2,
  HardDrive,
  DollarSign,
  Play,
  Square,
  ArrowRight,
  TrendingUp,
} from 'lucide-react'
import { DashboardData } from '../lib/types'
import { NavTab } from '../components/NavSidebar'

interface Props {
  data: DashboardData | null
  onNavigate: (tab: NavTab) => void
  onStartSource: (id: string) => Promise<void>
  onStopSource: (id: string) => Promise<void>
}

export const Dashboard: React.FC<Props> = ({
  data,
  onNavigate,
  onStartSource,
  onStopSource,
}) => {
  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400">
        Loading dashboard metrics...
      </div>
    )
  }

  const activeStreams = data.sources.filter(
    (s) => s.status === 'recording' || s.status === 'processing'
  )

  return (
    <div className="p-8 space-y-8 max-w-7xl mx-auto">
      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Active Streams */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Active Streams</span>
            <Radio className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-slate-100">{activeStreams.length}</div>
          <p className="text-[11px] text-slate-400 mt-1">
            {data.sources.length} total stream sources configured
          </p>
        </div>

        {/* Chunks Processed */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Chunks Done</span>
            <TrendingUp className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-bold text-slate-100">{data.total_chunks}</div>
          <p className="text-[11px] text-slate-400 mt-1">90s segments sliced & ingested</p>
        </div>

        {/* Clips Generated */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Clips Made</span>
            <Scissors className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-2xl font-bold text-slate-100">{data.total_clips}</div>
          <p className="text-[11px] text-slate-400 mt-1">
            <span className="text-amber-400 font-semibold">{data.pending_review}</span> awaiting review
          </p>
        </div>

        {/* Posts Today */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Posts Today</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-slate-100">{data.posts_today}</div>
          <p className="text-[11px] text-slate-400 mt-1">Published across all accounts</p>
        </div>

        {/* Gemini Spend */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Gemini Spend</span>
            <DollarSign className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-slate-100">
            ${data.gemini_spend_usd.toFixed(2)}
          </div>
          <p className="text-[11px] text-slate-400 mt-1">
            Cap: ${data.gemini_cap_usd.toFixed(2)} {data.cap_hit && '(Hit)'}
          </p>
        </div>
      </div>

      {/* Active Streams Section */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="font-bold text-slate-100 text-sm flex items-center gap-2">
            <Radio className="w-4 h-4 text-indigo-400" />
            Configured Stream Sources
          </h3>
          <button
            onClick={() => onNavigate('sources')}
            className="text-xs font-semibold text-indigo-400 hover:text-indigo-300 flex items-center gap-1 transition"
          >
            Manage Sources <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {data.sources.length === 0 ? (
          <div className="p-8 text-center text-slate-400 text-sm">
            No stream sources added yet.{' '}
            <button
              onClick={() => onNavigate('sources')}
              className="text-indigo-400 underline hover:text-indigo-300 font-medium"
            >
              Add your first live stream or video
            </button>
          </div>
        ) : (
          <div className="divide-y divide-slate-800">
            {data.sources.map((src) => {
              const isRunning = src.status === 'recording' || src.status === 'processing'
              return (
                <div key={src.id} className="p-4 flex items-center justify-between hover:bg-slate-800/30 transition">
                  <div className="space-y-1 max-w-lg">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm text-slate-200">
                        {src.label || src.url}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                          isRunning
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                            : src.status === 'error'
                            ? 'bg-rose-500/20 text-rose-300'
                            : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {src.status}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 truncate font-mono">{src.url}</p>
                    <div className="flex items-center gap-4 text-xs text-slate-400">
                      <span>Chunk: {src.chunk_seconds}s</span>
                      <span>Overlap: {src.overlap_seconds}s</span>
                      <span>Done: {src.chunks_done || 0} chunks</span>
                      <span>Clips: {src.clips_made || 0} made</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {isRunning ? (
                      <button
                        onClick={() => onStopSource(src.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 rounded-lg text-xs font-semibold transition"
                      >
                        <Square className="w-3.5 h-3.5 fill-current" />
                        Stop
                      </button>
                    ) : (
                      <button
                        onClick={() => onStartSource(src.id)}
                        className="flex items-center gap-1.5 px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow transition"
                      >
                        <Play className="w-3.5 h-3.5 fill-current" />
                        Start Pipeline
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Review Quick Action Banner */}
      {data.pending_review > 0 && (
        <div className="bg-gradient-to-r from-indigo-900/40 via-purple-900/30 to-slate-900 border border-indigo-500/30 rounded-xl p-6 flex items-center justify-between shadow-lg">
          <div className="space-y-1">
            <h4 className="text-base font-bold text-slate-100 flex items-center gap-2">
              <Scissors className="w-5 h-5 text-indigo-400" />
              {data.pending_review} New Short Clips Ready for Review!
            </h4>
            <p className="text-xs text-slate-300">
              AI moment detection extracted vertical 9:16 shorts. Preview, edit titles, and approve them for multi-account publishing.
            </p>
          </div>
          <button
            onClick={() => onNavigate('clips')}
            className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-lg text-sm shadow-md shadow-indigo-600/30 transition flex items-center gap-2"
          >
            Open Clips Review <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}
