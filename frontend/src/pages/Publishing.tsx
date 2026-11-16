import React, { useState } from 'react'
import {
  Send,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RotateCcw,
  Calendar,
  Filter,
} from 'lucide-react'
import { Account, Clip, PostJob } from '../lib/types'

interface Props {
  posts: PostJob[]
  accounts: Account[]
  clips: Clip[]
  onRetryPost: (postId: string) => Promise<void>
  onRefresh: () => void
}

export const Publishing: React.FC<Props> = ({
  posts,
  accounts,
  clips,
  onRetryPost,
  onRefresh,
}) => {
  const [filterPlatform, setFilterPlatform] = useState<string>('all')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [retryingId, setRetryingId] = useState<string | null>(null)

  const accountMap = new Map(accounts.map((a) => [a.id, a]))
  const clipMap = new Map(clips.map((c) => [c.id, c]))

  const filteredPosts = posts.filter((p) => {
    if (filterPlatform !== 'all' && p.platform !== filterPlatform) return false
    if (filterStatus !== 'all' && p.status !== filterStatus) return false
    return true
  })

  const handleRetry = async (postId: string) => {
    setRetryingId(postId)
    try {
      await onRetryPost(postId)
      onRefresh()
    } finally {
      setRetryingId(null)
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Send className="w-5 h-5 text-indigo-400" />
            Social Publishing Queue
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Idempotent publication log for every (clip, account, platform) dispatch.
          </p>
        </div>

        <button
          onClick={onRefresh}
          className="flex items-center gap-2 px-3.5 py-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 rounded-lg text-xs font-semibold transition"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh Queue
        </button>
      </div>

      {/* Spam Prevention Banner */}
      <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-4 flex items-start gap-3 text-xs text-amber-200">
        <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <span className="font-semibold text-amber-300">Spam Guard & Platform Protection:</span>
          <p className="text-amber-200/80 leading-relaxed">
            Posting identical titles and descriptions simultaneously across multiple accounts risks platform spam penalties. Clipper automatically applies random jitter between account dispatches, enforces minimum intervals, and appends custom account suffixes/hashtags.
          </p>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="flex items-center gap-4 bg-slate-900 p-3 rounded-xl border border-slate-800 text-xs">
        <div className="flex items-center gap-2">
          <Filter className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-slate-400 font-medium">Filter Platform:</span>
          <select
            value={filterPlatform}
            onChange={(e) => setFilterPlatform(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-slate-200 focus:outline-none"
          >
            <option value="all">All Platforms</option>
            <option value="youtube">YouTube</option>
            <option value="instagram">Instagram</option>
            <option value="tiktok">TikTok</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-slate-400 font-medium">Status:</span>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-slate-200 focus:outline-none"
          >
            <option value="all">All Statuses</option>
            <option value="posted">Posted</option>
            <option value="pending">Pending</option>
            <option value="scheduled">Scheduled</option>
            <option value="failed">Failed</option>
            <option value="dry_run">Dry Run</option>
            <option value="cooldown">Cooldown</option>
          </select>
        </div>

        <span className="text-slate-400 ml-auto">
          Showing <strong className="text-slate-200">{filteredPosts.length}</strong> jobs
        </span>
      </div>

      {/* Jobs Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        {filteredPosts.length === 0 ? (
          <div className="p-16 text-center space-y-2">
            <Send className="w-10 h-10 text-slate-700 mx-auto" />
            <h3 className="text-sm font-semibold text-slate-300">No publishing jobs in queue</h3>
            <p className="text-xs text-slate-400">
              Approved clips published to target accounts will appear here.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-950/60 text-slate-400 uppercase text-[10px] font-bold tracking-wider">
                  <th className="py-3 px-4">Clip</th>
                  <th className="py-3 px-4">Account</th>
                  <th className="py-3 px-4">Platform</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Request / Time</th>
                  <th className="py-3 px-4">Error / Details</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {filteredPosts.map((post) => {
                  const clip = clipMap.get(post.clip_id)
                  const account = accountMap.get(post.account_id)
                  const isRetrying = retryingId === post.id

                  return (
                    <tr key={post.id} className="hover:bg-slate-800/20 transition">
                      {/* Clip */}
                      <td className="py-3 px-4 font-medium text-slate-200 max-w-xs truncate">
                        {clip?.title || post.clip_id.slice(0, 12)}
                      </td>

                      {/* Account */}
                      <td className="py-3 px-4 text-slate-300">
                        {account?.label || post.account_id.slice(0, 8)}
                      </td>

                      {/* Platform */}
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                            post.platform === 'youtube'
                              ? 'bg-rose-500/20 text-rose-300'
                              : post.platform === 'instagram'
                              ? 'bg-pink-500/20 text-pink-300'
                              : 'bg-cyan-500/20 text-cyan-300'
                          }`}
                        >
                          {post.platform}
                        </span>
                      </td>

                      {/* Status */}
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                            post.status === 'posted'
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : post.status === 'failed'
                              ? 'bg-rose-500/20 text-rose-300'
                              : post.status === 'scheduled'
                              ? 'bg-purple-500/20 text-purple-300'
                              : post.status === 'cooldown'
                              ? 'bg-amber-500/20 text-amber-300'
                              : 'bg-blue-500/20 text-blue-300'
                          }`}
                        >
                          {post.status}
                        </span>
                      </td>

                      {/* Request / Time */}
                      <td className="py-3 px-4 font-mono text-[11px] text-slate-400">
                        {post.posted_at
                          ? new Date(post.posted_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                          : post.scheduled_at
                          ? new Date(post.scheduled_at * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                          : post.request_id
                          ? post.request_id.slice(0, 14)
                          : '—'}
                      </td>

                      {/* Error */}
                      <td className="py-3 px-4 text-slate-400 max-w-xs truncate text-[11px]">
                        {post.error ? (
                          <span className="text-rose-400 font-mono" title={post.error}>
                            {post.error}
                          </span>
                        ) : post.status === 'posted' ? (
                          <span className="text-emerald-400 flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3" /> Live
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>

                      {/* Action */}
                      <td className="py-3 px-4 text-right">
                        {post.status === 'failed' && (
                          <button
                            onClick={() => handleRetry(post.id)}
                            disabled={isRetrying}
                            className="p-1 px-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-[11px] font-semibold transition inline-flex items-center gap-1"
                          >
                            <RotateCcw className={`w-3 h-3 ${isRetrying ? 'animate-spin' : ''}`} />
                            Retry
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
