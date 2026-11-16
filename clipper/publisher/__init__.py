"""Publisher abstractions and platform implementations for Live Stream Clipper."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ClipRecord:
    """Represents a clip ready for publication."""

    id: str
    job_id: str
    title: str
    path: Path
    approved: int = 1
    posted_platforms: List[str] = field(default_factory=list)
    created_at: float = 0.0
    description: Optional[str] = None
    clip_index: int = 0
    raw_metadata: Optional[Dict[str, Any]] = None


class Publisher(ABC):
    """Abstract Base Class for social media publishers."""

    @abstractmethod
    def post(self, clip: ClipRecord, dry_run: bool = False) -> str:
        """Publish a clip to the platform.

        Args:
            clip: ClipRecord containing clip metadata and video path.
            dry_run: If True, simulate publishing without modifying remote platform.

        Returns:
            Platform-specific post ID, remote request ID, or 'dry_run'.
        """

    @abstractmethod
    def check_token(self) -> bool:
        """Validate credentials / tokens against the platform API.

        Returns:
            True if credentials are valid, False if authentication has expired.
        """
