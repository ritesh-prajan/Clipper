import React, { useState } from 'react'
import {
  Scissors,
  CheckCircle2,
  XCircle,
  Play,
  Share2,
  Edit2,
  Check,
  Filter,
  Sparkles,
  Layers,
} from 'lucide-react'
import { Account, Clip } from '../lib/types'

interface Props {
  clips: Clip[]
  accounts: Account[]
  onApproveClip: (id: string, newTitle?: string, targetAccountIds?: string[]) => Promise<void>
  onRejectClip: (id: string) => Promise<void>
  onUpdateClip: (id: string, data: { title?: string; description?: string }) => Promise<void>
  onBulkAction: (ids: string[], action: 'approve' | 'reject') => Promise<void>
  onQuickPost: (clipId: string, accountIds: string[]) => Promise<void>
}

export const Clips: React.FC<Props> = ({
  clips,
  accounts,
  onApproveClip,
  onRejectClip,
  onUpdateClip,
  onBulkAction,
  onQuickPost,
}) => {
  const [filterStatus, setFilterStatus] = useState<'pending' | 'approved' | 'rejected' | 'all'>('pending')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedClipIds, setSelectedClipIds] = useState<string[]>([])
  const [editingClipId, setEditingClipId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [publishModalClip, setPublishModalClip] = useState<Clip | null>(null)
  const [targetAccountIds, setTargetAccountIds] = useState<string[]>([])

  const filteredClips = clips.filter((c) => {
    if (filterStatus === 'pending' && c.approved !== 0) return false
    if (filterStatus === 'approved' && c.approved !== 1) return false
    if (filterStatus === 'rejected' && c.approved !== -1) return false
    if (searchTerm) {
      const match = c.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
                    c.path.toLowerCase().includes(searchTerm.toLowerCase())
      if (!match) return false
    }
    return true
  })

  const toggleSelect = (id: string) => {
    setSelectedClipIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    )
  }

  const selectAll = () => {
    if (selectedClipIds.length === filteredClips.length) {
      setSelectedClipIds([])
    } else {
      setSelectedClipIds(filteredClips.map((c) => c.id))
    }
  }

  const startEdit = (clip: Clip) => {
    setEditingClipId(clip.id)
    setEditTitle(clip.title)
  }

  const saveEdit = async (id: string) => {
    if (editTitle.trim()) {
      await onUpdateClip(id, { title: editTitle.trim() })
    }
    setEditingClipId(null)
  }

  const handleBulkApprove = async () => {
    if (selectedClipIds.length === 0) return
    await onBulkAction(selectedClipIds, 'approve')
    setSelectedClipIds([])
  }

  const handleBulkReject = async () => {
    if (selectedClipIds.length === 0) return
    await onBulkAction(selectedClipIds, 'reject')
    setSelectedClipIds([])
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Filter and Actions Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Scissors className="w-5 h-5 text-indigo-400" />
            AI Clips Gallery
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Vertical 9:16 shorts extracted by OpenShorts. Review, refine captions, and publish.
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-2 bg-slate-900 p-1 rounded-xl border border-slate-800 text-xs font-semibold">
          {(['pending', 'approved', 'rejected', 'all'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setFilterStatus(s)}
              className={`px-3 py-1.5 rounded-lg capitalize transition ${
                filterStatus === s
                  ? 'bg-indigo-600 text-white shadow'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {s === 'pending' ? 'Pending Review' : s}
            </button>
          ))}
        </div>
      </div>

      {/* Search and Bulk Actions Toolbar */}
      <div className="flex items-center justify-between gap-4 bg-slate-900 p-3 rounded-xl border border-slate-800">
        <div className="flex items-center gap-3 flex-1">
          <input
            type="text"
            placeholder="Search clips by title or filename..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full max-w-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
          <span className="text-xs text-slate-400">
            Showing <strong className="text-slate-200">{filteredClips.length}</strong> of {clips.length} clips
          </span>
        </div>

        {filteredClips.length > 0 && (
          <div className="flex items-center gap-2">
            <button
              onClick={selectAll}
              className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 bg-slate-800 rounded-lg transition"
            >
              {selectedClipIds.length === filteredClips.length ? 'Deselect All' : 'Select All'}
            </button>
            {selectedClipIds.length > 0 && (
              <>
                <button
                  onClick={handleBulkApprove}
                  className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow transition flex items-center gap-1.5"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Approve ({selectedClipIds.length})
                </button>
                <button
                  onClick={handleBulkReject}
                  className="px-3.5 py-1.5 bg-rose-600/30 hover:bg-rose-600/40 text-rose-300 border border-rose-500/30 rounded-lg text-xs font-semibold transition flex items-center gap-1.5"
                >
                  <XCircle className="w-3.5 h-3.5" />
                  Reject ({selectedClipIds.length})
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Clips Grid */}
      {filteredClips.length === 0 ? (
        <div className="p-16 text-center bg-slate-900 border border-slate-800 rounded-2xl space-y-3">
          <Scissors className="w-12 h-12 text-slate-700 mx-auto" />
          <h3 className="text-base font-semibold text-slate-300">No clips found</h3>
          <p className="text-xs text-slate-400 max-w-sm mx-auto">
            {filterStatus === 'pending'
              ? 'All generated clips have been reviewed or streams are currently recording.'
              : 'Try changing your filter or searching for another title.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredClips.map((clip) => {
            const isSelected = selectedClipIds.includes(clip.id)
            const isEditing = editingClipId === clip.id

            return (
              <div
                key={clip.id}
                className={`bg-slate-900 border rounded-2xl overflow-hidden flex flex-col transition shadow-sm ${
                  isSelected ? 'border-indigo-500 ring-2 ring-indigo-500/20' : 'border-slate-800 hover:border-slate-700'
                }`}
              >
                {/* 9:16 Video Player Container */}
                <div className="relative aspect-[9/16] bg-black overflow-hidden group">
                  <video
                    controls
                    preload="metadata"
                    src={`/api/clips/${clip.id}/video`}
                    className="w-full h-full object-contain"
                  />

                  {/* Top Overlay Badges */}
                  <div className="absolute top-2.5 left-2.5 right-2.5 flex items-center justify-between pointer-events-none">
                    {/* Checkbox */}
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(clip.id)}
                      className="pointer-events-auto rounded border-slate-700 bg-slate-900/80 text-indigo-600 focus:ring-0 w-4 h-4 cursor-pointer"
                    />

                    {/* Virality score badge if available */}
                    {clip.virality_score && (
                      <span className="px-2 py-0.5 rounded-full bg-amber-500/90 text-black text-[10px] font-extrabold flex items-center gap-1 shadow">
                        <Sparkles className="w-3 h-3" />
                        {clip.virality_score.toFixed(1)}/10
                      </span>
                    )}

                    {/* Status badge */}
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                        clip.approved === 1
                          ? 'bg-emerald-500/80 text-white'
                          : clip.approved === -1
                          ? 'bg-rose-500/80 text-white'
                          : 'bg-amber-500/80 text-black font-extrabold'
                      }`}
                    >
                      {clip.approved === 1 ? 'Approved' : clip.approved === -1 ? 'Rejected' : 'Review'}
                    </span>
                  </div>
                </div>

                {/* Details and Actions */}
                <div className="p-4 flex-1 flex flex-col justify-between space-y-3">
                  <div className="space-y-1.5">
                    {isEditing ? (
                      <div className="flex items-center gap-1.5">
                        <input
                          type="text"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                          autoFocus
                        />
                        <button
                          onClick={() => saveEdit(clip.id)}
                          className="p-1 bg-emerald-600 text-white rounded hover:bg-emerald-500"
                        >
                          <Check className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-start justify-between gap-2 group/title">
                        <h4 className="font-semibold text-slate-100 text-xs leading-snug line-clamp-2">
                          {clip.title}
                        </h4>
                        <button
                          onClick={() => startEdit(clip)}
                          className="opacity-0 group-hover/title:opacity-100 p-1 text-slate-400 hover:text-slate-200 transition shrink-0"
                          title="Edit title"
                        >
                          <Edit2 className="w-3 h-3" />
                        </button>
                      </div>
                    )}

                    <p className="text-[10px] text-slate-400 truncate font-mono">
                      {clip.path.split(/[\\/]/).pop()}
                    </p>

                    {clip.posted_platforms.length > 0 && (
                      <div className="flex items-center gap-1 pt-1">
                        <span className="text-[10px] text-slate-400">Posted to:</span>
                        {clip.posted_platforms.map((p) => (
                          <span
                            key={p}
                            className="px-1.5 py-0.5 rounded bg-slate-800 text-[9px] font-bold uppercase text-slate-300"
                          >
                            {p}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Action Buttons */}
                  <div className="pt-2 border-t border-slate-800/80 flex items-center gap-2">
                    {clip.approved === 0 ? (
                      <>
                        <button
                          onClick={() => onApproveClip(clip.id)}
                          className="flex-1 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow transition flex items-center justify-center gap-1"
                        >
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Approve
                        </button>
                        <button
                          onClick={() => onRejectClip(clip.id)}
                          className="px-3 py-1.5 bg-slate-800 hover:bg-rose-900/40 text-slate-400 hover:text-rose-300 rounded-lg text-xs font-semibold transition"
                        >
                          Reject
                        </button>
                      </>
                    ) : clip.approved === 1 ? (
                      <button
                        onClick={() => {
                          setPublishModalClip(clip)
                          setTargetAccountIds(accounts.map((a) => a.id))
                        }}
                        className="w-full py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow transition flex items-center justify-center gap-1.5"
                      >
                        <Share2 className="w-3.5 h-3.5" />
                        Publish to Accounts
                      </button>
                    ) : (
                      <button
                        onClick={() => onApproveClip(clip.id)}
                        className="w-full py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition"
                      >
                        Restore & Approve
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Publish Modal */}
      {publishModalClip && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-in fade-in duration-150">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="font-bold text-slate-100 text-sm flex items-center gap-2">
                <Share2 className="w-4 h-4 text-indigo-400" />
                Publish Clip to Social Media
              </h3>
              <button
                onClick={() => setPublishModalClip(null)}
                className="text-slate-400 hover:text-slate-200"
              >
                ✕
              </button>
            </div>

            <div className="space-y-1">
              <span className="text-xs font-medium text-slate-400">Clip Title:</span>
              <p className="text-sm font-semibold text-slate-200 bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                {publishModalClip.title}
              </p>
            </div>

            {/* Target Accounts Selection */}
            <div>
              <span className="text-xs font-medium text-slate-400 block mb-1.5">
                Select Destination Accounts:
              </span>
              {accounts.length === 0 ? (
                <p className="text-xs text-amber-400 bg-amber-500/10 p-3 rounded-lg border border-amber-500/20">
                  No social accounts configured. Go to the Social Accounts tab to connect YouTube, Instagram, or TikTok.
                </p>
              ) : (
                <div className="space-y-1.5 max-h-40 overflow-y-auto bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                  {accounts.map((acc) => (
                    <label
                      key={acc.id}
                      className="flex items-center gap-2 text-xs text-slate-200 hover:text-white cursor-pointer select-none"
                    >
                      <input
                        type="checkbox"
                        checked={targetAccountIds.includes(acc.id)}
                        onChange={() => {
                          setTargetAccountIds((prev) =>
                            prev.includes(acc.id)
                              ? prev.filter((id) => id !== acc.id)
                              : [...prev, acc.id]
                          )
                        }}
                        className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                      />
                      <span>{acc.label}</span>
                      <span className="text-[10px] text-slate-400">
                        ({acc.platforms_enabled.join(', ')})
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <p className="text-[11px] text-slate-400 italic">
              Posts will be staggered with jitter to avoid spam filters. Each account's daily limits and minimum gap are enforced automatically.
            </p>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-800">
              <button
                onClick={() => setPublishModalClip(null)}
                className="px-3.5 py-2 text-xs font-semibold text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                disabled={targetAccountIds.length === 0}
                onClick={async () => {
                  await onQuickPost(publishModalClip.id, targetAccountIds)
                  setPublishModalClip(null)
                }}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg text-xs font-semibold shadow transition"
              >
                Publish Now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
