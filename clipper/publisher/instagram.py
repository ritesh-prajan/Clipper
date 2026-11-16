"""Instagram Reels Publisher stub for direct Instagram Graph API publishing.

Requirements and API Documentation:
- API: Instagram Graph API (Container upload & publish)
- Docs: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/content-publishing
- Required Credentials:
  - Meta Business Account with linked Instagram Professional (Creator/Business) account.
  - Facebook App with `instagram_basic`, `instagram_content_publish` permissions.
  - Long-lived User / Page Access Token.
  - Publicly accessible HTTPS video URL (Instagram requires downloading via URL).
"""

from clipper.publisher import ClipRecord, Publisher


class InstagramPublisher(Publisher):
    """Direct Instagram Reels publisher stub."""

    def __init__(self, access_token: str = ""):
        self.access_token = access_token

    def check_token(self) -> bool:
        """Verify Instagram User/Page access token validity."""
        # TODO: Implement token debug check via /debug_token endpoint
        return False

    def post(self, clip: ClipRecord, dry_run: bool = False) -> str:
        """Upload video to Instagram Reels via Graph API.

        Raises:
            NotImplementedError: Direct Instagram publisher is a stub. Use UploadPostPublisher instead.
        """
        raise NotImplementedError(
            "Direct Instagram Reels publishing via Instagram Graph API is not yet implemented.\n"
            "To publish to Instagram Reels:\n"
            "  1. Use 'upload_post' publisher via Upload-Post relay (recommended), OR\n"
            "  2. Create a media container (POST /{ig-user-id}/media with media_type=REELS),\n"
            "     poll container status, and publish (POST /{ig-user-id}/media_publish).\n"
            "Reference: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/content-publishing"
        )
