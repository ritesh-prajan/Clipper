export interface Account {
  id: string
  label: string
  upload_post_api_key_masked: string
  profile_name?: string
  platforms_enabled: string[]
  enabled: boolean
  daily_limit_youtube: number
  daily_limit_instagram: number
  daily_limit_tiktok: number
  min_gap_seconds: number
  timezone: string
  auto_approve: boolean
  caption_suffix: string
  created_at: number
}

export interface Source {
  id: string
  url: string
  label?: string
  chunk_seconds: number
  overlap_seconds: number
  max_clips: number
  i_own_or_have_permission: boolean
  status: 'idle' | 'recording' | 'processing' | 'offline' | 'stopped' | 'error' | string
  target_account_ids: string[]
  output_dir?: string
  created_at: number
  chunks_done?: number
  clips_made?: number
}

export interface Clip {
  id: string
  job_id: string
  title: string
  path: string
  approved: number // 0=pending, 1=approved, -1=rejected
  posted_platforms: string[]
  created_at: number
  virality_score?: number
  description?: string
}

export interface PostJob {
  id: string
  clip_id: string
  account_id: string
  platform: string
  status: 'pending' | 'posted' | 'failed' | 'scheduled' | 'dry_run' | 'cooldown' | 'skipped'
  request_id?: string
  error?: string
  scheduled_at?: number
  posted_at?: number
  created_at: number
}

export interface Settings {
  openshorts_url: string
  max_disk_gb: number
  auto_approve_global: boolean
  dry_run: boolean
  gemini_spend_cap_usd: number
  has_password: boolean
  output_dir: string
  bind_host: string
}

export interface DashboardData {
  sources: Source[]
  total_chunks: number
  total_clips: number
  pending_review: number
  posts_today: number
  disk_used_gb: number
  disk_cap_gb: number
  gemini_spend_usd: number
  gemini_cap_usd: number
  cap_hit: boolean
}

export interface LogLine {
  level: string
  logger: string
  message: string
  timestamp: number
}
