"""Configuration management for Live Stream Clipper using Pydantic v2 BaseSettings."""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type, Union

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# Global holder for dynamic YAML path resolution across settings instances
_ACTIVE_YAML_PATH: Optional[Path] = None


class _DynamicYamlSettingsSource(YamlConfigSettingsSource):
    """YAML settings source resolving to the user-specified config file path or config.yaml."""

    def __init__(self, settings_cls: Type[BaseSettings]):
        global _ACTIVE_YAML_PATH
        target_path = _ACTIVE_YAML_PATH if _ACTIVE_YAML_PATH is not None else Path("config.yaml")
        super().__init__(settings_cls, yaml_file=target_path)


class AppConfig(BaseSettings):
    """Application settings loaded from YAML configuration and environment variables.

    Loading order:
    1. Explicit kwargs passed to constructor (CLI overrides)
    2. Environment variables / .env
    3. YAML config file (default: config.yaml)
    4. Field defaults
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    stream_urls: List[str] = Field(
        default_factory=list,
        description="List of live stream URLs (Twitch, YouTube, Kick, RTMP/HLS).",
    )
    i_own_or_have_permission: bool = Field(
        default=False,
        description="Affirmation of copyright ownership or license to process and publish stream content.",
    )
    chunk_seconds: int = Field(
        default=600,
        description="Duration of each segment in seconds.",
    )
    overlap_seconds: int = Field(
        default=20,
        description="Overlap between consecutive segments in seconds to avoid cutting moments at boundaries.",
    )
    max_workers: int = Field(
        default=2,
        description="Maximum concurrent OpenShorts chunk processing tasks.",
    )
    max_offline_seconds: int = Field(
        default=3600,
        description="Maximum seconds to keep retrying reconnection when a stream is offline before stopping.",
    )
    max_disk_gb: float = Field(
        default=20.0,
        description="Maximum disk capacity in GB allocated to the output directory before pruning old chunks.",
    )
    openshorts_url: str = Field(
        default="http://localhost:8000",
        description="Base URL of the OpenShorts REST API.",
    )
    openshorts_api_key: Optional[str] = Field(
        default=None,
        repr=False,
        description="API key for OpenShorts Cloud (never printed or logged).",
    )
    job_timeout_seconds: int = Field(
        default=1200,
        description="Maximum seconds to wait for an OpenShorts processing job to complete.",
    )
    poll_initial_seconds: float = Field(
        default=5.0,
        description="Initial polling interval in seconds for job status.",
    )
    poll_max_seconds: float = Field(
        default=60.0,
        description="Maximum polling interval in seconds under exponential backoff.",
    )
    output_dir: Path = Field(
        default=Path("./live_output"),
        description="Root output directory for chunks, shorts, reviews, and SQLite database.",
    )
    cleanup_chunks: bool = Field(
        default=False,
        description="Whether to immediately delete raw chunk video files after clip extraction.",
    )
    auto_approve: bool = Field(
        default=False,
        description="If True, generated clips skip review and are marked approved immediately.",
    )
    dry_run: bool = Field(
        default=False,
        description="Simulate pipeline actions without uploading to OpenShorts or posting to social media.",
    )
    platforms: List[str] = Field(
        default_factory=lambda: ["upload_post"],
        description="Target social media destinations or publisher backends.",
    )
    daily_post_limit: Dict[str, int] = Field(
        default_factory=lambda: {"upload_post": 10},
        description="Maximum posts allowed per 24-hour sliding window per platform.",
    )
    min_post_gap_seconds: int = Field(
        default=300,
        description="Minimum quiet time in seconds required between consecutive social posts.",
    )
    upload_post_api_key: Optional[str] = Field(
        default=None,
        repr=False,
        description="Upload-Post API key for social media relay (never logged).",
    )
    quality: str = Field(
        default="best",
        description="Stream quality selector for streamlink / yt-dlp.",
    )
    ffprobe_check: bool = Field(
        default=True,
        description="Validate video container integrity via ffprobe before ingesting a chunk.",
    )
    server_retry_max_attempts: int = Field(
        default=0,
        description="Number of retry attempts if OpenShorts server is unreachable at startup (0 = fail immediately).",
    )
    server_retry_backoff: float = Field(
        default=2.0,
        description="Initial backoff in seconds between OpenShorts server reachability retries.",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """Configure source precedence: CLI/init -> Env vars -> .env -> YAML file -> Defaults."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _DynamicYamlSettingsSource(settings_cls),
            file_secret_settings,
        )

    @classmethod
    def load(
        cls,
        config_path: Optional[Union[str, Path]] = None,
        **overrides,
    ) -> "AppConfig":
        """Load configuration from a YAML file path with optional keyword overrides.

        Args:
            config_path: Path to the YAML file. Defaults to config.yaml if present.
            **overrides: Direct overrides with highest priority (e.g., CLI arguments).

        Returns:
            Validated AppConfig instance.
        """
        global _ACTIVE_YAML_PATH
        if config_path:
            _ACTIVE_YAML_PATH = Path(config_path)
        else:
            _ACTIVE_YAML_PATH = Path("config.yaml")

        try:
            cfg = cls(**overrides)
        finally:
            _ACTIVE_YAML_PATH = None

        return cfg

    def check_copyright_permission(self, raise_on_error: bool = False) -> bool:
        """Verify copyright permission declaration and print a warning if not set.

        Args:
            raise_on_error: If True and i_own_or_have_permission is False, raise PermissionError.

        Returns:
            True if permission affirmed, False otherwise.
        """
        if not self.i_own_or_have_permission:
            sys.stderr.write(
                "\n"
                "====================================================================\n"
                "⚠️  COPYRIGHT NOTICE & USAGE WARNING\n"
                "====================================================================\n"
                "You have not affirmed content ownership or license rights\n"
                "(i_own_or_have_permission is false or unset).\n"
                "Automated social posting and clipping without authorization from the\n"
                "copyright owner may violate platform terms of service and copyright laws.\n"
                "Set 'i_own_or_have_permission: true' in config.yaml once confirmed.\n"
                "====================================================================\n\n"
            )
            if raise_on_error:
                raise PermissionError("Publishing refused: 'i_own_or_have_permission' is false.")
            return False
        return True
