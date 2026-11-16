import { Account, Clip, DashboardData, PostJob, Settings, Source } from './types'

const API_BASE = ''

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  headers.set('X-Requested-With', 'XMLHttpRequest')
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })

  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('auth-required'))
    throw new Error('Authentication required')
  }

  if (!res.ok) {
    let errMessage = `HTTP ${res.status}`
    try {
      const errJson = await res.json()
      errMessage = errJson.detail || errJson.message || errMessage
    } catch {
      // ignore
    }
    throw new Error(errMessage)
  }

  if (res.status === 204) {
    return {} as T
  }

  return res.json()
}

export const api = {
  // Auth
  login: (password: string) =>
    request<{ ok: boolean; message: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  getAuthStatus: () =>
    request<{ authenticated: boolean; auth_required: boolean }>('/auth/status'),

  // Dashboard
  getDashboard: () => request<DashboardData>('/api/dashboard'),

  // Sources
  getSources: () => request<Source[]>('/api/sources'),
  createSource: (data: Partial<Source>) =>
    request<Source>('/api/sources', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  uploadSource: (formData: FormData) =>
    request<Source>('/api/sources/upload', {
      method: 'POST',
      body: formData,
    }),
  updateSource: (id: string, data: Partial<Source>) =>
    request<Source>(`/api/sources/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteSource: (id: string) =>
    request<void>(`/api/sources/${id}`, { method: 'DELETE' }),
  startSource: (id: string) =>
    request<{ started: boolean }>(`/api/sources/${id}/start`, { method: 'POST' }),
  stopSource: (id: string) =>
    request<{ stopped: boolean }>(`/api/sources/${id}/stop`, { method: 'POST' }),

  // Clips
  getClips: (status?: string) =>
    request<Clip[]>(`/api/clips${status ? `?status=${status}` : ''}`),
  getClip: (id: string) => request<Clip>(`/api/clips/${id}`),
  updateClip: (id: string, data: { title?: string; description?: string }) =>
    request<Clip>(`/api/clips/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  approveClip: (id: string, new_title?: string, target_account_ids?: string[]) =>
    request<Clip>(`/api/clips/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ new_title, target_account_ids }),
    }),
  rejectClip: (id: string) =>
    request<Clip>(`/api/clips/${id}/reject`, { method: 'POST' }),
  bulkAction: (clip_ids: string[], action: 'approve' | 'reject') =>
    request<Array<{ clip_id: string; ok: boolean }>>('/api/clips/bulk', {
      method: 'POST',
      body: JSON.stringify({ clip_ids, action }),
    }),

  // Accounts
  getAccounts: () => request<Account[]>('/api/accounts'),
  createAccount: (data: any) =>
    request<Account>('/api/accounts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateAccount: (id: string, data: any) =>
    request<Account>(`/api/accounts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteAccount: (id: string) =>
    request<void>(`/api/accounts/${id}`, { method: 'DELETE' }),
  testAccount: (id: string) =>
    request<{ ok: boolean; profiles: any[]; error?: string }>(
      `/api/accounts/${id}/test`,
      { method: 'POST' }
    ),

  // Publishing
  getPosts: (params?: { clip_id?: string; account_id?: string; status?: string }) => {
    const q = new URLSearchParams(params as any).toString()
    return request<PostJob[]>(`/api/posts${q ? `?${q}` : ''}`)
  },
  getPostQueue: () => request<PostJob[]>('/api/posts/queue'),
  postClip: (data: {
    clip_id: string
    account_ids: string[]
    platforms?: string[]
    title_override?: string
    caption_override?: string
    schedule_at?: number
    dry_run?: boolean
  }) =>
    request<any[]>('/api/posts/post', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  retryPost: (postId: string) =>
    request<{ ok: boolean }>(`/api/posts/${postId}/retry`, { method: 'POST' }),

  // Settings
  getSettings: () => request<Settings>('/api/settings'),
  updateSettings: (data: Partial<Settings> & { auth_password?: string }) =>
    request<Settings>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Logs
  getRecentLogs: () => request<{ logs: any[] }>('/api/logs/recent'),
}
