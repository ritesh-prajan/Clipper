import React from 'react'
import {
  LayoutDashboard,
  Radio,
  Scissors,
  Users,
  Send,
  Settings,
  Terminal,
  LogOut,
  Sparkles,
} from 'lucide-react'

export type NavTab = 'dashboard' | 'sources' | 'clips' | 'accounts' | 'publishing' | 'settings' | 'logs'

interface Props {
  currentTab: NavTab
  onSelectTab: (tab: NavTab) => void
  pendingReviewCount?: number
  hasPassword?: boolean
  onLogout?: () => void
}

export const NavSidebar: React.FC<Props> = ({
  currentTab,
  onSelectTab,
  pendingReviewCount = 0,
  hasPassword = false,
  onLogout,
}) => {
  const navItems: Array<{ id: NavTab; label: string; icon: React.ReactNode; badge?: number }> = [
    { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
    { id: 'sources', label: 'Streams & Sources', icon: <Radio className="w-5 h-5" /> },
    {
      id: 'clips',
      label: 'Clips Gallery',
      icon: <Scissors className="w-5 h-5" />,
      badge: pendingReviewCount > 0 ? pendingReviewCount : undefined,
    },
    { id: 'accounts', label: 'Social Accounts', icon: <Users className="w-5 h-5" /> },
    { id: 'publishing', label: 'Publishing Queue', icon: <Send className="w-5 h-5" /> },
    { id: 'logs', label: 'Live Logs', icon: <Terminal className="w-5 h-5" /> },
    { id: 'settings', label: 'Settings', icon: <Settings className="w-5 h-5" /> },
  ]

  return (
    <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0 select-none">
      {/* Brand Header */}
      <div className="h-16 px-6 flex items-center gap-3 border-b border-slate-800">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <Sparkles className="w-5 h-5 text-white" />
        </div>
        <div>
          <h1 className="text-base font-bold text-slate-100 tracking-tight leading-none">Clipper</h1>
          <span className="text-[10px] text-slate-400 font-medium uppercase tracking-wider">OpusClip Studio</span>
        </div>
      </div>

      {/* Nav List */}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = currentTab === item.id
          return (
            <button
              key={item.id}
              onClick={() => onSelectTab(item.id)}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-lg text-sm font-medium transition ${
                isActive
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              <div className="flex items-center gap-3">
                {item.icon}
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && (
                <span
                  className={`px-2 py-0.5 rounded-full text-xs font-bold ${
                    isActive ? 'bg-white text-indigo-700' : 'bg-indigo-500/20 text-indigo-400'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
        <span className="truncate">Local-first Studio</span>
        {hasPassword && onLogout && (
          <button
            onClick={onLogout}
            title="Log out"
            className="p-1.5 hover:bg-slate-800 rounded text-slate-400 hover:text-red-400 transition"
          >
            <LogOut className="w-4 h-4" />
          </button>
        )}
      </div>
    </aside>
  )
}
