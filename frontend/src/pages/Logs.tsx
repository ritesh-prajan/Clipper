import React, { useEffect, useRef, useState } from 'react'
import {
  Terminal,
  Filter,
  Trash2,
  ArrowDownCircle,
  Copy,
  Check,
  Search,
} from 'lucide-react'
import { LogLine } from '../lib/types'
import { api } from '../lib/api'

export const LogsPage: React.FC = () => {
  const [logs, setLogs] = useState<LogLine[]>([])
  const [levelFilter, setLevelFilter] = useState<string>('ALL')
  const [searchQuery, setSearchQuery] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [copied, setCopied] = useState(false)
  const logContainerRef = useRef<HTMLDivElement>(null)

  // Fetch initial recent logs
  useEffect(() => {
    api.getRecentLogs().then((res) => {
      if (res && res.logs) {
        setLogs(res.logs)
      }
    }).catch(() => {})

    // Connect SSE
    const es = new EventSource('/api/logs/stream')
    es.addEventListener('log_line', (event: MessageEvent) => {
      try {
        const line = JSON.parse(event.data) as LogLine
        setLogs((prev) => [...prev.slice(-2000), line])
      } catch {
        // ignore parse error
      }
    })

    return () => {
      es.close()
    }
  }, [])

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const filteredLogs = logs.filter((log) => {
    if (levelFilter !== 'ALL' && log.level !== levelFilter) return false
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      return (
        log.message.toLowerCase().includes(q) ||
        log.logger.toLowerCase().includes(q)
      )
    }
    return true
  })

  const copyAll = () => {
    const text = filteredLogs
      .map(
        (l) =>
          `[${new Date(l.timestamp * 1000).toLocaleTimeString()}] [${l.level}] [${l.logger}] ${l.message}`
      )
      .join('\n')
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const clearLogs = () => {
    setLogs([])
  }

  return (
    <div className="p-8 max-w-7xl mx-auto h-[calc(100vh-4rem)] flex flex-col space-y-4">
      {/* Top Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 shrink-0">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Terminal className="w-5 h-5 text-indigo-400" />
            Live Pipeline Logs
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Streaming real-time logs from FFmpeg recorder, OpenShorts processor, and publishing workers. Secrets are redacted automatically.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={copyAll}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition flex items-center gap-1.5"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'Copied' : 'Copy Logs'}
          </button>
          <button
            onClick={clearLogs}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition flex items-center gap-1.5"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Clear
          </button>
        </div>
      </div>

      {/* Filter and Control Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900 p-3 rounded-xl border border-slate-800 shrink-0 text-xs">
        <div className="flex items-center gap-3 flex-1 min-w-[280px]">
          <div className="relative flex-1 max-w-xs">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
            <input
              type="text"
              placeholder="Search logs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">Level:</span>
            <select
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-slate-200 focus:outline-none"
            >
              <option value="ALL">ALL Levels</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer select-none text-slate-300">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
            />
            <span className="flex items-center gap-1">
              <ArrowDownCircle className="w-3.5 h-3.5 text-slate-400" />
              Auto-scroll
            </span>
          </label>

          <span className="text-slate-400 font-mono">
            {filteredLogs.length} line(s)
          </span>
        </div>
      </div>

      {/* Terminal Output Window */}
      <div
        ref={logContainerRef}
        className="flex-1 bg-slate-950 border border-slate-800 rounded-2xl p-4 overflow-y-auto font-mono text-xs space-y-1 shadow-inner select-text"
      >
        {filteredLogs.length === 0 ? (
          <div className="h-full flex items-center justify-center text-slate-600">
            No log entries match the current filter.
          </div>
        ) : (
          filteredLogs.map((l, i) => {
            const timeStr = new Date(l.timestamp * 1000).toLocaleTimeString()
            const isError = l.level === 'ERROR'
            const isWarn = l.level === 'WARNING'
            return (
              <div
                key={i}
                className={`leading-relaxed flex items-start gap-2 hover:bg-slate-900/50 px-1.5 py-0.5 rounded ${
                  isError ? 'text-rose-400 bg-rose-500/5' : isWarn ? 'text-amber-300' : 'text-slate-300'
                }`}
              >
                <span className="text-slate-600 shrink-0 select-none">[{timeStr}]</span>
                <span
                  className={`px-1.5 py-0.2 rounded text-[10px] font-bold uppercase shrink-0 select-none ${
                    isError
                      ? 'bg-rose-500/20 text-rose-300'
                      : isWarn
                      ? 'bg-amber-500/20 text-amber-300'
                      : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {l.level}
                </span>
                <span className="text-slate-500 shrink-0 select-none">[{l.logger}]</span>
                <span className="break-all whitespace-pre-wrap">{l.message}</span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
