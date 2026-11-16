import React, { useState } from 'react'
import {
  Plus,
  Play,
  Square,
  Trash2,
  Upload,
  Link,
  ShieldCheck,
  AlertCircle,
  Film,
  Radio,
} from 'lucide-react'
import { Account, Source } from '../lib/types'

interface Props {
  sources: Source[]
  accounts: Account[]
  onRefresh: () => void
  onStartSource: (id: string) => Promise<void>
  onStopSource: (id: string) => Promise<void>
  onCreateSource: (data: Partial<Source>) => Promise<void>
  onUploadSource: (formData: FormData) => Promise<void>
  onDeleteSource: (id: string) => Promise<void>
}

export const Sources: React.FC<Props> = ({
  sources,
  accounts,
  onStartSource,
  onStopSource,
  onCreateSource,
  onUploadSource,
  onDeleteSource,
}) => {
  const [showModal, setShowModal] = useState(false)
  const [sourceType, setSourceType] = useState<'url' | 'upload'>('url')
  const [url, setUrl] = useState('')
  const [label, setLabel] = useState('')
  const [chunkSeconds, setChunkSeconds] = useState(90)
  const [overlapSeconds, setOverlapSeconds] = useState(15)
  const [maxClips, setMaxClips] = useState(10)
  const [iOwnOrHavePermission, setIOwnOrHavePermission] = useState(false)
  const [selectedAccountIds, setSelectedAccountIds] = useState<string[]>([])
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      if (sourceType === 'url') {
        if (!url) {
          setError('Stream URL is required')
          setIsSubmitting(false)
          return
        }
        await onCreateSource({
          url,
          label: label || undefined,
          chunk_seconds: Number(chunkSeconds),
          overlap_seconds: Number(overlapSeconds),
          max_clips: Number(maxClips),
          i_own_or_have_permission: iOwnOrHavePermission,
          target_account_ids: selectedAccountIds,
        })
      } else {
        if (!uploadFile) {
          setError('Please select a video file to upload')
          setIsSubmitting(false)
          return
        }
        const formData = new FormData()
        formData.append('file', uploadFile)
        if (label) formData.append('label', label)
        formData.append('chunk_seconds', String(chunkSeconds))
        formData.append('overlap_seconds', String(overlapSeconds))
        formData.append('max_clips', String(maxClips))
        formData.append('i_own_or_have_permission', String(iOwnOrHavePermission))
        formData.append('target_account_ids', JSON.stringify(selectedAccountIds))

        await onUploadSource(formData)
      }

      setShowModal(false)
      // Reset form
      setUrl('')
      setLabel('')
      setUploadFile(null)
      setIOwnOrHavePermission(false)
      setSelectedAccountIds([])
    } catch (err: any) {
      setError(err.message || 'Failed to add source')
    } finally {
      setIsSubmitting(false)
    }
  }

  const toggleAccount = (accId: string) => {
    setSelectedAccountIds((prev) =>
      prev.includes(accId) ? prev.filter((id) => id !== accId) : [...prev, accId]
    )
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Top action header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100">Stream & Video Sources</h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Manage live stream feeds and uploaded videos being sliced into vertical shorts.
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold shadow-md shadow-indigo-600/30 transition"
        >
          <Plus className="w-4 h-4" />
          Add Source
        </button>
      </div>

      {/* Sources List */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm divide-y divide-slate-800">
        {sources.length === 0 ? (
          <div className="p-12 text-center space-y-3">
            <Radio className="w-10 h-10 text-slate-600 mx-auto" />
            <h3 className="text-base font-semibold text-slate-300">No sources added yet</h3>
            <p className="text-xs text-slate-400 max-w-sm mx-auto">
              Paste a YouTube / Twitch / RTMP live stream link or upload an existing video file to start auto-clipping.
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="mt-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow transition"
            >
              Add Your First Source
            </button>
          </div>
        ) : (
          sources.map((src) => {
            const isRunning = src.status === 'recording' || src.status === 'processing'
            return (
              <div key={src.id} className="p-5 flex items-center justify-between hover:bg-slate-800/30 transition">
                <div className="space-y-2 max-w-2xl">
                  <div className="flex items-center gap-3">
                    <span className="font-bold text-slate-100 text-sm">
                      {src.label || 'Stream Source'}
                    </span>
                    <span
                      className={`px-2.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                        isRunning
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : src.status === 'error'
                          ? 'bg-rose-500/20 text-rose-300'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {src.status}
                    </span>
                    {src.i_own_or_have_permission ? (
                      <span className="flex items-center gap-1 text-[11px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                        <ShieldCheck className="w-3.5 h-3.5" /> Rights Confirmed
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[11px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                        <AlertCircle className="w-3.5 h-3.5" /> Review-only (No Permission)
                      </span>
                    )}
                  </div>

                  <p className="text-xs text-slate-400 font-mono truncate">{src.url}</p>

                  <div className="flex items-center gap-4 text-xs text-slate-400">
                    <span>
                      Chunk:{' '}
                      <strong className="text-slate-300">{src.chunk_seconds}s</strong>
                    </span>
                    <span>
                      Overlap:{' '}
                      <strong className="text-slate-300">{src.overlap_seconds}s</strong>
                    </span>
                    <span>
                      Chunks Done:{' '}
                      <strong className="text-slate-300">{src.chunks_done || 0}</strong>
                    </span>
                    <span>
                      Clips Generated:{' '}
                      <strong className="text-indigo-400 font-bold">{src.clips_made || 0}</strong>
                    </span>
                    {src.target_account_ids?.length > 0 && (
                      <span>
                        Target Accounts:{' '}
                        <strong className="text-slate-300">{src.target_account_ids.length}</strong>
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {isRunning ? (
                    <button
                      onClick={() => onStopSource(src.id)}
                      className="flex items-center gap-1.5 px-3.5 py-1.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 rounded-lg text-xs font-semibold transition"
                    >
                      <Square className="w-3.5 h-3.5 fill-current" />
                      Stop Pipeline
                    </button>
                  ) : (
                    <button
                      onClick={() => onStartSource(src.id)}
                      className="flex items-center gap-1.5 px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow transition"
                    >
                      <Play className="w-3.5 h-3.5 fill-current" />
                      Start
                    </button>
                  )}

                  <button
                    onClick={() => {
                      if (confirm(`Delete source "${src.label || src.url}"?`)) {
                        onDeleteSource(src.id)
                      }
                    }}
                    className="p-1.5 text-slate-500 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition"
                    title="Delete source"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Add Source Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-in fade-in duration-150">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                <Radio className="w-5 h-5 text-indigo-400" />
                Add Stream or Video Source
              </h3>
              <button
                onClick={() => setShowModal(false)}
                className="text-slate-400 hover:text-slate-200 text-sm font-semibold"
              >
                ✕
              </button>
            </div>

            {error && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-lg text-xs text-rose-300">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Type Switcher */}
              <div className="grid grid-cols-2 gap-2 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs font-semibold">
                <button
                  type="button"
                  onClick={() => setSourceType('url')}
                  className={`py-2 rounded flex items-center justify-center gap-2 transition ${
                    sourceType === 'url' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Link className="w-3.5 h-3.5" />
                  Live Stream URL
                </button>
                <button
                  type="button"
                  onClick={() => setSourceType('upload')}
                  className={`py-2 rounded flex items-center justify-center gap-2 transition ${
                    sourceType === 'upload' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Upload className="w-3.5 h-3.5" />
                  Upload Video File
                </button>
              </div>

              {sourceType === 'url' ? (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Live Stream URL (Twitch, YouTube, Kick, RTMP)
                  </label>
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://www.youtube.com/watch?v=... or https://twitch.tv/..."
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                    required
                  />
                </div>
              ) : (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Select Local Video File (MP4, MKV, MOV)
                  </label>
                  <input
                    type="file"
                    accept="video/*"
                    onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-indigo-600 file:text-white"
                    required
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Source Label (Optional)
                </label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="e.g. GTA 6 Live Stream Day 1"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
              </div>

              {/* Chunk Settings */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Chunk Length (sec)
                  </label>
                  <input
                    type="number"
                    min="15"
                    max="3600"
                    value={chunkSeconds}
                    onChange={(e) => setChunkSeconds(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                  <span className="text-[10px] text-slate-400">OpenShorts needs ≥45s</span>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Overlap (sec)
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="300"
                    value={overlapSeconds}
                    onChange={(e) => setOverlapSeconds(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                  <span className="text-[10px] text-slate-400">Avoid cutting key moments</span>
                </div>
              </div>

              {/* Target Accounts Selection */}
              {accounts.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Default Auto-Post Target Accounts
                  </label>
                  <div className="space-y-1.5 max-h-32 overflow-y-auto bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                    {accounts.map((acc) => (
                      <label
                        key={acc.id}
                        className="flex items-center gap-2 text-xs text-slate-300 hover:text-white cursor-pointer select-none"
                      >
                        <input
                          type="checkbox"
                          checked={selectedAccountIds.includes(acc.id)}
                          onChange={() => toggleAccount(acc.id)}
                          className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                        />
                        <span>{acc.label}</span>
                        <span className="text-slate-400 text-[10px]">({acc.platforms_enabled.join(', ')})</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {/* Ownership Gate Checkbox */}
              <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 space-y-2">
                <label className="flex items-start gap-2.5 text-xs text-slate-200 cursor-pointer select-none font-medium">
                  <input
                    type="checkbox"
                    checked={iOwnOrHavePermission}
                    onChange={(e) => setIOwnOrHavePermission(e.target.checked)}
                    className="mt-0.5 rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                  />
                  <span>
                    I own or have permission to use this content.
                  </span>
                </label>
                <p className="text-[11px] text-slate-400 pl-6 leading-relaxed">
                  Publishing to social networks is blocked without this affirmation. Recording and clipping to the review folder will still run.
                </p>
              </div>

              {/* Modal Actions */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-xs font-semibold text-slate-400 hover:text-slate-200 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition"
                >
                  {isSubmitting ? 'Adding...' : 'Add Source'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
