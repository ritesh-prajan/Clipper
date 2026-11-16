import React, { useEffect, useState } from 'react'
import { Header } from './components/Header'
import { NavSidebar, NavTab } from './components/NavSidebar'
import { SpendCapBanner } from './components/SpendCapBanner'
import { Accounts } from './pages/Accounts'
import { Clips } from './pages/Clips'
import { Dashboard } from './pages/Dashboard'
import { Login } from './pages/Login'
import { LogsPage } from './pages/Logs'
import { Publishing } from './pages/Publishing'
import { SettingsPage } from './pages/Settings'
import { Sources } from './pages/Sources'
import { api } from './lib/api'
import { Account, Clip, DashboardData, PostJob, Settings, Source } from './lib/types'

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<NavTab>('dashboard')
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(true)
  const [authRequired, setAuthRequired] = useState<boolean>(false)

  // App data state
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [clips, setClips] = useState<Clip[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [posts, setPosts] = useState<PostJob[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)

  // Check initial auth status
  useEffect(() => {
    api.getAuthStatus().then((status) => {
      setIsAuthenticated(status.authenticated)
      setAuthRequired(status.auth_required)
    }).catch(() => {})

    const handleAuthReq = () => {
      setIsAuthenticated(false)
      setAuthRequired(true)
    }
    window.addEventListener('auth-required', handleAuthReq)
    return () => window.removeEventListener('auth-required', handleAuthReq)
  }, [])

  // Load and refresh core data
  const refreshData = async () => {
    try {
      const [dashData, srcData, clipData, accData, postData, settData] = await Promise.all([
        api.getDashboard(),
        api.getSources(),
        api.getClips('all'),
        api.getAccounts(),
        api.getPostQueue(),
        api.getSettings(),
      ])
      setDashboard(dashData)
      setSources(srcData)
      setClips(clipData)
      setAccounts(accData)
      setPosts(postData)
      setSettings(settData)
    } catch {
      // ignore unauthenticated or network errors
    }
  }

  // Periodic refresh
  useEffect(() => {
    if (!isAuthenticated && authRequired) return
    refreshData()
    const timer = setInterval(refreshData, 4000)
    return () => clearInterval(timer)
  }, [isAuthenticated, authRequired])

  // Login handler
  const handleLogin = async (password: string) => {
    const res = await api.login(password)
    if (res.ok) {
      setIsAuthenticated(true)
      refreshData()
      return true
    }
    return false
  }

  const handleLogout = async () => {
    await api.logout()
    setIsAuthenticated(false)
  }

  // Actions
  const handleStartSource = async (id: string) => {
    await api.startSource(id)
    refreshData()
  }

  const handleStopSource = async (id: string) => {
    await api.stopSource(id)
    refreshData()
  }

  const handleCreateSource = async (data: Partial<Source>) => {
    await api.createSource(data)
    refreshData()
  }

  const handleUploadSource = async (formData: FormData) => {
    await api.uploadSource(formData)
    refreshData()
  }

  const handleDeleteSource = async (id: string) => {
    await api.deleteSource(id)
    refreshData()
  }

  const handleApproveClip = async (id: string, newTitle?: string, targetAccountIds?: string[]) => {
    await api.approveClip(id, newTitle, targetAccountIds)
    refreshData()
  }

  const handleRejectClip = async (id: string) => {
    await api.rejectClip(id)
    refreshData()
  }

  const handleUpdateClip = async (id: string, data: { title?: string; description?: string }) => {
    await api.updateClip(id, data)
    refreshData()
  }

  const handleBulkAction = async (ids: string[], action: 'approve' | 'reject') => {
    await api.bulkAction(ids, action)
    refreshData()
  }

  const handleQuickPost = async (clipId: string, accountIds: string[]) => {
    await api.postClip({ clip_id: clipId, account_ids: accountIds })
    refreshData()
  }

  const handleCreateAccount = async (data: any) => {
    await api.createAccount(data)
    refreshData()
  }

  const handleUpdateAccount = async (id: string, data: any) => {
    await api.updateAccount(id, data)
    refreshData()
  }

  const handleDeleteAccount = async (id: string) => {
    await api.deleteAccount(id)
    refreshData()
  }

  const handleRetryPost = async (postId: string) => {
    await api.retryPost(postId)
    refreshData()
  }

  const handleSaveSettings = async (data: any) => {
    await api.updateSettings(data)
    refreshData()
  }

  if (authRequired && !isAuthenticated) {
    return <Login onLogin={handleLogin} />
  }

  const activeStreamsCount = sources.filter(
    (s) => s.status === 'recording' || s.status === 'processing'
  ).length

  return (
    <div className="flex h-screen bg-[#0b0f19] text-slate-100 font-sans overflow-hidden">
      {/* Navigation Sidebar */}
      <NavSidebar
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
        pendingReviewCount={dashboard?.pending_review || 0}
        hasPassword={settings?.has_password}
        onLogout={handleLogout}
      />

      {/* Main Viewport */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Persistent Spend Cap Banner */}
        {dashboard?.cap_hit && (
          <SpendCapBanner
            spend={dashboard.gemini_spend_usd}
            cap={dashboard.gemini_cap_usd}
            onNavigateSettings={() => setCurrentTab('settings')}
          />
        )}

        {/* Header */}
        <Header
          title={
            currentTab === 'dashboard'
              ? 'Studio Overview'
              : currentTab === 'sources'
              ? 'Stream Feeds & Video Sources'
              : currentTab === 'clips'
              ? 'Clips Review & Curation'
              : currentTab === 'accounts'
              ? 'Connected Social Profiles'
              : currentTab === 'publishing'
              ? 'Publishing Queue & Log'
              : currentTab === 'logs'
              ? 'Real-Time Pipeline Console'
              : 'Pipeline Configuration'
          }
          subtitle={
            currentTab === 'dashboard'
              ? 'Real-time metrics, stream ingestion status, and social activity.'
              : undefined
          }
          diskUsedGb={dashboard?.disk_used_gb || 0}
          diskCapGb={dashboard?.disk_cap_gb || 20}
          spendUsd={dashboard?.gemini_spend_usd || 0}
          spendCapUsd={dashboard?.gemini_cap_usd || 10}
          activeStreamsCount={activeStreamsCount}
        />

        {/* Content Body */}
        <main className="flex-1 overflow-y-auto bg-slate-950/40">
          {currentTab === 'dashboard' && (
            <Dashboard
              data={dashboard}
              onNavigate={setCurrentTab}
              onStartSource={handleStartSource}
              onStopSource={handleStopSource}
            />
          )}

          {currentTab === 'sources' && (
            <Sources
              sources={sources}
              accounts={accounts}
              onRefresh={refreshData}
              onStartSource={handleStartSource}
              onStopSource={handleStopSource}
              onCreateSource={handleCreateSource}
              onUploadSource={handleUploadSource}
              onDeleteSource={handleDeleteSource}
            />
          )}

          {currentTab === 'clips' && (
            <Clips
              clips={clips}
              accounts={accounts}
              onApproveClip={handleApproveClip}
              onRejectClip={handleRejectClip}
              onUpdateClip={handleUpdateClip}
              onBulkAction={handleBulkAction}
              onQuickPost={handleQuickPost}
            />
          )}

          {currentTab === 'accounts' && (
            <Accounts
              accounts={accounts}
              onRefresh={refreshData}
              onCreateAccount={handleCreateAccount}
              onUpdateAccount={handleUpdateAccount}
              onDeleteAccount={handleDeleteAccount}
            />
          )}

          {currentTab === 'publishing' && (
            <Publishing
              posts={posts}
              accounts={accounts}
              clips={clips}
              onRetryPost={handleRetryPost}
              onRefresh={refreshData}
            />
          )}

          {currentTab === 'settings' && (
            <SettingsPage
              settings={settings}
              onSave={handleSaveSettings}
            />
          )}

          {currentTab === 'logs' && <LogsPage />}
        </main>
      </div>
    </div>
  )
}

export default App
