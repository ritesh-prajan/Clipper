import React, { useState } from 'react'
import {
  Settings as SettingsIcon,
  HardDrive,
  DollarSign,
  ShieldAlert,
  Save,
  CheckCircle2,
  Lock,
  Server,
} from 'lucide-react'
import { Settings } from '../lib/types'

interface Props {
  settings: Settings | null
  onSave: (data: Partial<Settings> & { auth_password?: string }) => Promise<void>
}

export const SettingsPage: React.FC<Props> = ({ settings, onSave }) => {
  if (!settings) {
    return <div className="p-8 text-slate-400">Loading settings...</div>
  }

  const [openshortsUrl, setOpenshortsUrl] = useState(settings.openshorts_url)
  const [maxDiskGb, setMaxDiskGb] = useState(settings.max_disk_gb)
  const [autoApproveGlobal, setAutoApproveGlobal] = useState(settings.auto_approve_global)
  const [dryRun, setDryRun] = useState(settings.dry_run)
  const [geminiSpendCapUsd, setGeminiSpendCapUsd] = useState(settings.gemini_spend_cap_usd)
  const [password, setPassword] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsSaving(true)
    setSaveSuccess(false)

    try {
      const payload: any = {
        openshorts_url: openshortsUrl,
        max_disk_gb: Number(maxDiskGb),
        auto_approve_global: autoApproveGlobal,
        dry_run: dryRun,
        gemini_spend_cap_usd: Number(geminiSpendCapUsd),
      }
      if (password) {
        payload.auth_password = password
      }

      await onSave(payload)
      setPassword('')
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
          <SettingsIcon className="w-5 h-5 text-indigo-400" />
          Pipeline Settings
        </h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Configure local OpenShorts connection, resource guardrails, budget caps, and authentication.
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* OpenShorts Server Configuration */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-100 border-b border-slate-800 pb-3">
            <Server className="w-4 h-4 text-indigo-400" />
            OpenShorts Backend Connection
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              OpenShorts REST API Base URL
            </label>
            <input
              type="url"
              required
              value={openshortsUrl}
              onChange={(e) => setOpenshortsUrl(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
            />
            <span className="text-[11px] text-slate-400 mt-1 block">
              Default is <code className="text-slate-300">http://localhost:8000</code>. On WSL2, verify port forwarding or specify direct host address.
            </span>
          </div>

          <div className="flex items-center justify-between pt-2">
            <div>
              <span className="text-xs font-semibold text-slate-200 block">Dry Run Mode</span>
              <span className="text-[11px] text-slate-400">
                Log and simulate actions without calling external AI models or social endpoints.
              </span>
            </div>
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0 w-4 h-4 cursor-pointer"
            />
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-slate-800/80">
            <div>
              <span className="text-xs font-semibold text-slate-200 block">Global Auto-Approve</span>
              <span className="text-[11px] text-slate-400">
                Automatically approve all extracted clips and bypass the manual review folder.
              </span>
            </div>
            <input
              type="checkbox"
              checked={autoApproveGlobal}
              onChange={(e) => setAutoApproveGlobal(e.target.checked)}
              className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0 w-4 h-4 cursor-pointer"
            />
          </div>
        </div>

        {/* Resource Guardrails & Gemini Spend Cap */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-100 border-b border-slate-800 pb-3">
            <DollarSign className="w-4 h-4 text-emerald-400" />
            Budget & Disk Guardrails
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Gemini Spend Cap (USD $)
              </label>
              <input
                type="number"
                step="0.50"
                min="0"
                value={geminiSpendCapUsd}
                onChange={(e) => setGeminiSpendCapUsd(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">
                Stops sending chunks to OpenShorts once this spend ceiling is reached. Shows a persistent banner in UI. (0 = unlimited)
              </span>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Max Output Disk Space (GB)
              </label>
              <input
                type="number"
                min="1"
                value={maxDiskGb}
                onChange={(e) => setMaxDiskGb(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-1 block">
                Automatically prunes oldest completed chunks when live_output directory exceeds this limit.
              </span>
            </div>
          </div>
        </div>

        {/* Security & Password Login */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-100 border-b border-slate-800 pb-3">
            <Lock className="w-4 h-4 text-purple-400" />
            Password Protection & Security
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Single-User Password Login {settings.has_password ? '(Password Currently Active)' : '(Currently Inactive)'}
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={settings.has_password ? 'Enter new password to change' : 'Set a password to enable login requirement'}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
            />
            <span className="text-[11px] text-slate-400 mt-1 block">
              Required if binding to a non-localhost network interface. Leave blank to keep existing password.
            </span>
          </div>

          <div className="text-xs text-slate-400 bg-slate-950 p-3 rounded-lg border border-slate-800 space-y-1">
            <div className="font-semibold text-slate-300">Bound Host: {settings.bind_host}</div>
            <div>Output Directory: <code className="text-slate-300">{settings.output_dir}</code></div>
          </div>
        </div>

        {/* Save Bar */}
        <div className="flex items-center justify-between pt-2">
          {saveSuccess ? (
            <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5 animate-in fade-in">
              <CheckCircle2 className="w-4 h-4" />
              Settings saved successfully!
            </span>
          ) : (
            <span />
          )}

          <button
            type="submit"
            disabled={isSaving}
            className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold rounded-lg text-sm shadow-md shadow-indigo-600/30 transition flex items-center gap-2"
          >
            <Save className="w-4 h-4" />
            {isSaving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </form>
    </div>
  )
}
