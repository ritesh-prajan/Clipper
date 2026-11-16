import React, { useState } from 'react'
import {
  Users,
  Plus,
  Key,
  CheckCircle2,
  AlertTriangle,
  Trash2,
  Edit2,
  RefreshCw,
  Clock,
  ShieldCheck,
  HelpCircle,
  ExternalLink,
} from 'lucide-react'
import { Account } from '../lib/types'
import { api } from '../lib/api'

interface Props {
  accounts: Account[]
  onRefresh: () => void
  onCreateAccount: (data: any) => Promise<void>
  onUpdateAccount: (id: string, data: any) => Promise<void>
  onDeleteAccount: (id: string) => Promise<void>
}

export const Accounts: React.FC<Props> = ({
  accounts,
  onRefresh,
  onCreateAccount,
  onUpdateAccount,
  onDeleteAccount,
}) => {
  const [showModal, setShowModal] = useState(false)
  const [editingAccount, setEditingAccount] = useState<Account | null>(null)

  // Form states
  const [label, setLabel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [profileName, setProfileName] = useState('')
  const [platforms, setPlatforms] = useState<string[]>(['youtube', 'instagram'])
  const [enabled, setEnabled] = useState(true)
  const [dailyLimitYt, setDailyLimitYt] = useState(10)
  const [dailyLimitIg, setDailyLimitIg] = useState(10)
  const [dailyLimitTt, setDailyLimitTt] = useState(5)
  const [minGapSeconds, setMinGapSeconds] = useState(300)
  const [timezone, setTimezone] = useState('UTC')
  const [autoApprove, setAutoApprove] = useState(false)
  const [captionSuffix, setCaptionSuffix] = useState('#Shorts #Viral')

  // Testing states: accountId -> result
  const [testResults, setTestResults] = useState<Record<string, { loading?: boolean; ok?: boolean; profiles?: any[]; error?: string }>>({})

  const openCreateModal = () => {
    setEditingAccount(null)
    setLabel('')
    setApiKey('')
    setProfileName('')
    setPlatforms(['youtube', 'instagram'])
    setEnabled(true)
    setDailyLimitYt(10)
    setDailyLimitIg(10)
    setDailyLimitTt(5)
    setMinGapSeconds(300)
    setTimezone('UTC')
    setAutoApprove(false)
    setCaptionSuffix('#Shorts #Viral')
    setShowModal(true)
  }

  const openEditModal = (acc: Account) => {
    setEditingAccount(acc)
    setLabel(acc.label)
    setApiKey('') // Leave blank unless changing
    setProfileName(acc.profile_name || '')
    setPlatforms(acc.platforms_enabled || ['youtube', 'instagram'])
    setEnabled(acc.enabled)
    setDailyLimitYt(acc.daily_limit_youtube)
    setDailyLimitIg(acc.daily_limit_instagram)
    setDailyLimitTt(acc.daily_limit_tiktok)
    setMinGapSeconds(acc.min_gap_seconds)
    setTimezone(acc.timezone)
    setAutoApprove(acc.auto_approve)
    setCaptionSuffix(acc.caption_suffix || '')
    setShowModal(true)
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    const payload: any = {
      label,
      profile_name: profileName || null,
      platforms_enabled: platforms,
      enabled,
      daily_limit_youtube: Number(dailyLimitYt),
      daily_limit_instagram: Number(dailyLimitIg),
      daily_limit_tiktok: Number(dailyLimitTt),
      min_gap_seconds: Number(minGapSeconds),
      timezone,
      auto_approve: autoApprove,
      caption_suffix: captionSuffix,
    }
    if (apiKey.trim()) {
      payload.upload_post_api_key = apiKey.trim()
    }

    if (editingAccount) {
      await onUpdateAccount(editingAccount.id, payload)
    } else {
      if (!apiKey.trim()) {
        alert('Upload-Post API key is required')
        return
      }
      payload.upload_post_api_key = apiKey.trim()
      await onCreateAccount(payload)
    }

    setShowModal(false)
  }

  const togglePlatform = (p: string) => {
    setPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]
    )
  }

  const handleTestConnection = async (accId: string) => {
    setTestResults((prev) => ({ ...prev, [accId]: { loading: true } }))
    try {
      const res = await api.testAccount(accId)
      setTestResults((prev) => ({
        ...prev,
        [accId]: { loading: false, ok: res.ok, profiles: res.profiles, error: res.error },
      }))
    } catch (err: any) {
      setTestResults((prev) => ({
        ...prev,
        [accId]: { loading: false, ok: false, error: err.message },
      }))
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Users className="w-5 h-5 text-indigo-400" />
            Multi-Account Publishing
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Configure target YouTube, Instagram Reels, and TikTok accounts with isolated rate limits and staggered jitter.
          </p>
        </div>
        <button
          onClick={openCreateModal}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold shadow-md shadow-indigo-600/30 transition"
        >
          <Plus className="w-4 h-4" />
          Add Account
        </button>
      </div>

      {/* Info Callout */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-start gap-3 text-xs text-slate-300">
        <HelpCircle className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <span className="font-semibold text-slate-200">How Multi-Account Publishing Works:</span>
          <p className="text-slate-400 leading-relaxed">
            You can connect multiple YouTube, Instagram, and TikTok accounts. If using one Upload-Post API key with multiple profiles, enter the specific profile username. If using separate Upload-Post API keys, add each one as a distinct account. Keys are stored locally encrypted with Fernet and never displayed again. Failures on TikTok never block publishing to YouTube or Instagram.
          </p>
        </div>
      </div>

      {/* Accounts List */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {accounts.length === 0 ? (
          <div className="col-span-full p-16 text-center bg-slate-900 border border-slate-800 rounded-2xl space-y-3">
            <Users className="w-12 h-12 text-slate-700 mx-auto" />
            <h3 className="text-base font-semibold text-slate-300">No social accounts configured</h3>
            <p className="text-xs text-slate-400 max-w-sm mx-auto">
              Add your Upload-Post API key to enable 1-click or automated publishing to YouTube Shorts, Instagram Reels, and TikTok.
            </p>
            <button
              onClick={openCreateModal}
              className="mt-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow transition"
            >
              Add First Account
            </button>
          </div>
        ) : (
          accounts.map((acc) => {
            const test = testResults[acc.id]
            return (
              <div
                key={acc.id}
                className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-sm hover:border-slate-700 transition flex flex-col justify-between"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-bold text-slate-100 text-sm flex items-center gap-2">
                        {acc.label}
                        {!acc.enabled && (
                          <span className="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded uppercase">
                            Disabled
                          </span>
                        )}
                      </h3>
                      {acc.profile_name && (
                        <p className="text-xs text-slate-400 font-mono mt-0.5">
                          Profile: @{acc.profile_name}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => openEditModal(acc)}
                        className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded transition"
                        title="Edit Account"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Delete account "${acc.label}"?`)) {
                            onDeleteAccount(acc.id)
                          }
                        }}
                        className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded transition"
                        title="Delete Account"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {/* Masked Key */}
                  <div className="flex items-center gap-2 bg-slate-950 px-2.5 py-1.5 rounded-lg border border-slate-800 text-xs font-mono text-slate-400">
                    <Key className="w-3.5 h-3.5 text-slate-500" />
                    <span>{acc.upload_post_api_key_masked}</span>
                    <span className="ml-auto text-[10px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded font-sans font-semibold">
                      Encrypted
                    </span>
                  </div>

                  {/* Enabled Platforms Pills */}
                  <div className="space-y-1">
                    <span className="text-[11px] font-medium text-slate-400">Platforms Enabled:</span>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {['youtube', 'instagram', 'tiktok'].map((p) => {
                        const isEnabled = acc.platforms_enabled.includes(p)
                        return (
                          <span
                            key={p}
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              isEnabled
                                ? p === 'youtube'
                                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                  : p === 'instagram'
                                  ? 'bg-pink-500/20 text-pink-300 border border-pink-500/30'
                                  : 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                                : 'bg-slate-800 text-slate-500 opacity-40 line-through'
                            }`}
                          >
                            {p}
                          </span>
                        )
                      })}
                    </div>
                  </div>

                  {/* Limits and Settings */}
                  <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400 pt-2 border-t border-slate-800">
                    <div>
                      Daily Cap:{' '}
                      <strong className="text-slate-300">
                        YT {acc.daily_limit_youtube} / IG {acc.daily_limit_instagram}
                      </strong>
                    </div>
                    <div>
                      Min Gap:{' '}
                      <strong className="text-slate-300">{acc.min_gap_seconds}s</strong>
                    </div>
                    <div>
                      Timezone:{' '}
                      <strong className="text-slate-300">{acc.timezone}</strong>
                    </div>
                    <div>
                      Auto-Approve:{' '}
                      <strong className={acc.auto_approve ? 'text-emerald-400' : 'text-slate-400'}>
                        {acc.auto_approve ? 'Yes' : 'No'}
                      </strong>
                    </div>
                  </div>

                  {/* Test Connection Output */}
                  {test && (
                    <div className="pt-2 text-xs">
                      {test.loading ? (
                        <div className="text-slate-400 flex items-center gap-1.5">
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Verifying token...
                        </div>
                      ) : test.ok ? (
                        <div className="bg-emerald-500/10 border border-emerald-500/20 p-2.5 rounded-lg text-emerald-300 space-y-1">
                          <div className="flex items-center gap-1.5 font-semibold">
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                            Connected successfully!
                          </div>
                          {test.profiles && test.profiles.length > 0 && (
                            <p className="text-[10px] text-emerald-400">
                              Active: {test.profiles.map((pr: any) => `${pr.username} (${pr.connected?.join(', ') || 'none'})`).join('; ')}
                            </p>
                          )}
                        </div>
                      ) : (
                        <div className="bg-rose-500/10 border border-rose-500/20 p-2.5 rounded-lg text-rose-300 space-y-1">
                          <div className="flex items-center gap-1.5 font-semibold">
                            <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                            Connection failed / Reauth needed
                          </div>
                          <p className="text-[10px] text-rose-400 break-words">{test.error}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div className="pt-3 border-t border-slate-800">
                  <button
                    onClick={() => handleTestConnection(acc.id)}
                    disabled={test?.loading}
                    className="w-full py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold transition flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${test?.loading ? 'animate-spin' : ''}`} />
                    Test Connection
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Add / Edit Account Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-in fade-in duration-150">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="font-bold text-slate-100 text-sm flex items-center gap-2">
                <Users className="w-4 h-4 text-indigo-400" />
                {editingAccount ? 'Edit Account' : 'Add Social Media Account'}
              </h3>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-200">
                ✕
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Account Label</label>
                <input
                  type="text"
                  required
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="e.g. Primary YouTube Shorts Channel"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Upload-Post API Key{' '}
                  {editingAccount && <span className="text-slate-400 font-normal">(leave blank to keep existing)</span>}
                </label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={editingAccount ? '••••••••••••••••' : 'Enter API Key'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
                />
                <span className="text-[10px] text-slate-400 mt-1 block">
                  Stored locally encrypted with Fernet key at rest. Never shown again or logged.
                </span>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Profile Username (Optional)
                </label>
                <input
                  type="text"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  placeholder="e.g. gaming_shorts_daily (leave empty for default key profile)"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
                />
                <span className="text-[10px] text-slate-400 mt-1 block">
                  Allows multiple profiles under a single Upload-Post API key.
                </span>
              </div>

              {/* Platforms Enabled */}
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Publishing Platforms
                </label>
                <div className="flex items-center gap-3 bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                  {[
                    { id: 'youtube', label: 'YouTube Shorts' },
                    { id: 'instagram', label: 'Instagram Reels' },
                    { id: 'tiktok', label: 'TikTok (Optional)' },
                  ].map((plat) => (
                    <label key={plat.id} className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={platforms.includes(plat.id)}
                        onChange={() => togglePlatform(plat.id)}
                        className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                      />
                      <span>{plat.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Limits */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">YT Daily Cap</label>
                  <input
                    type="number"
                    min="0"
                    value={dailyLimitYt}
                    onChange={(e) => setDailyLimitYt(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">IG Daily Cap</label>
                  <input
                    type="number"
                    min="0"
                    value={dailyLimitIg}
                    onChange={(e) => setDailyLimitIg(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">TT Daily Cap</label>
                  <input
                    type="number"
                    min="0"
                    value={dailyLimitTt}
                    onChange={(e) => setDailyLimitTt(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">Min Gap (Seconds)</label>
                  <input
                    type="number"
                    min="0"
                    value={minGapSeconds}
                    onChange={(e) => setMinGapSeconds(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">Timezone</label>
                  <input
                    type="text"
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    placeholder="UTC or America/New_York"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Caption Hashtag Suffix (Optional)
                </label>
                <input
                  type="text"
                  value={captionSuffix}
                  onChange={(e) => setCaptionSuffix(e.target.value)}
                  placeholder="e.g. #Shorts #GTA6 #Gaming"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                />
                <span className="text-[10px] text-slate-400 mt-1 block">
                  Appended to clip captions. Varying hashtags per account prevents spam detection.
                </span>
              </div>

              {/* Toggles */}
              <div className="flex items-center gap-6 pt-2">
                <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                    className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                  />
                  <span>Account Enabled</span>
                </label>
                <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={autoApprove}
                    onChange={(e) => setAutoApprove(e.target.checked)}
                    className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                  />
                  <span>Auto-Approve to This Account</span>
                </label>
              </div>

              <div className="flex items-center justify-end gap-2 pt-4 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-3.5 py-2 text-xs font-semibold text-slate-400 hover:text-slate-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow transition"
                >
                  {editingAccount ? 'Update Account' : 'Save Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
