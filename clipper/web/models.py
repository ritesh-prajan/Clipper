"""Pydantic request/response models for the Clipper Web API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    ok: bool
    message: str = ""


# ── Accounts ──────────────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    upload_post_api_key: str = Field(..., min_length=1, description="Raw API key — stored encrypted")
    profile_name: Optional[str] = None
    platforms_enabled: List[str] = Field(default=["youtube", "instagram"])
    enabled: bool = True
    daily_limit_youtube: int = Field(default=10, ge=0, le=1000)
    daily_limit_instagram: int = Field(default=10, ge=0, le=1000)
    daily_limit_tiktok: int = Field(default=5, ge=0, le=1000)
    min_gap_seconds: int = Field(default=300, ge=0)
    timezone: str = "UTC"
    auto_approve: bool = False
    caption_suffix: str = ""

    @field_validator("platforms_enabled")
    @classmethod
    def validate_platforms(cls, v: List[str]) -> List[str]:
        allowed = {"youtube", "instagram", "tiktok"}
        invalid = [p for p in v if p not in allowed]
        if invalid:
            raise ValueError(f"Unknown platforms: {invalid}. Allowed: {allowed}")
        return v


class AccountUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    upload_post_api_key: Optional[str] = None  # None = keep existing
    profile_name: Optional[str] = None
    platforms_enabled: Optional[List[str]] = None
    enabled: Optional[bool] = None
    daily_limit_youtube: Optional[int] = Field(None, ge=0, le=1000)
    daily_limit_instagram: Optional[int] = Field(None, ge=0, le=1000)
    daily_limit_tiktok: Optional[int] = Field(None, ge=0, le=1000)
    min_gap_seconds: Optional[int] = Field(None, ge=0)
    timezone: Optional[str] = None
    auto_approve: Optional[bool] = None
    caption_suffix: Optional[str] = None


class AccountOut(BaseModel):
    id: str
    label: str
    upload_post_api_key_masked: str  # "••••••••{last4}"
    profile_name: Optional[str]
    platforms_enabled: List[str]
    enabled: bool
    daily_limit_youtube: int
    daily_limit_instagram: int
    daily_limit_tiktok: int
    min_gap_seconds: int
    timezone: str
    auto_approve: bool
    caption_suffix: str
    created_at: float


class AccountTestResult(BaseModel):
    ok: bool
    profiles: List[Dict[str, Any]] = []
    error: Optional[str] = None


# ── Sources ───────────────────────────────────────────────────────────────────

class SourceCreate(BaseModel):
    url: str = Field(..., min_length=1)
    label: Optional[str] = None
    chunk_seconds: int = Field(default=90, ge=1, le=3600)
    overlap_seconds: int = Field(default=15, ge=0, le=600)
    max_clips: int = Field(default=10, ge=1, le=100)
    i_own_or_have_permission: bool = False
    target_account_ids: List[str] = []


class SourceUpdate(BaseModel):
    url: Optional[str] = None
    label: Optional[str] = None
    chunk_seconds: Optional[int] = Field(None, ge=1, le=3600)
    overlap_seconds: Optional[int] = Field(None, ge=0, le=600)
    max_clips: Optional[int] = Field(None, ge=1, le=100)
    i_own_or_have_permission: Optional[bool] = None
    target_account_ids: Optional[List[str]] = None


class SourceOut(BaseModel):
    id: str
    url: str
    label: Optional[str]
    chunk_seconds: int
    overlap_seconds: int
    max_clips: int
    i_own_or_have_permission: bool
    status: str
    target_account_ids: List[str]
    output_dir: Optional[str]
    created_at: float
    # Runtime stats (populated by worker_manager)
    chunks_done: int = 0
    clips_made: int = 0


# ── Clips ─────────────────────────────────────────────────────────────────────

class ClipApprove(BaseModel):
    new_title: Optional[str] = None
    target_account_ids: Optional[List[str]] = None  # override source defaults


class ClipUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class ClipOut(BaseModel):
    id: str
    job_id: str
    title: str
    path: str
    approved: int  # 0=pending, 1=approved, -1=rejected
    posted_platforms: List[str]
    created_at: float
    source_id: Optional[str] = None
    virality_score: Optional[float] = None
    description: Optional[str] = None


class BulkAction(BaseModel):
    clip_ids: List[str]
    action: str  # "approve" | "reject"
    target_account_ids: Optional[List[str]] = None


# ── Publishing ────────────────────────────────────────────────────────────────

class PostRequest(BaseModel):
    clip_id: str
    account_ids: List[str]  # which accounts to post to
    platforms: Optional[List[str]] = None  # None = use each account's platforms_enabled
    title_override: Optional[str] = None
    caption_override: Optional[str] = None
    schedule_at: Optional[float] = None  # Unix timestamp; None = post now
    dry_run: bool = False


class PostOut(BaseModel):
    id: str
    clip_id: str
    account_id: str
    platform: str
    status: str
    request_id: Optional[str]
    error: Optional[str]
    scheduled_at: Optional[float]
    posted_at: Optional[float]
    created_at: float


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    openshorts_url: Optional[str] = None
    max_disk_gb: Optional[float] = Field(None, gt=0)
    auto_approve_global: Optional[bool] = None
    dry_run: Optional[bool] = None
    gemini_spend_cap_usd: Optional[float] = Field(None, ge=0)
    auth_password: Optional[str] = None  # set/clear password
    output_dir: Optional[str] = None
    bind_host: Optional[str] = None


class SettingsOut(BaseModel):
    openshorts_url: str
    max_disk_gb: float
    auto_approve_global: bool
    dry_run: bool
    gemini_spend_cap_usd: float
    has_password: bool
    output_dir: str
    bind_host: str


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardOut(BaseModel):
    sources: List[Dict[str, Any]]
    total_chunks: int
    total_clips: int
    pending_review: int
    posts_today: int
    disk_used_gb: float
    disk_cap_gb: float
    gemini_spend_usd: float
    gemini_cap_usd: float
    cap_hit: bool
