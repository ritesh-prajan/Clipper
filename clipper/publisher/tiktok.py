"""TikTok Publisher stub for direct TikTok Content Posting API.

Requirements and API Documentation:
- API: TikTok Content Posting API v2
- Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
- Required Credentials:
  - TikTok Developer Account and registered app with 'Direct Post' capability approval.
  - Client Key and Client Secret.
  - OAuth 2.0 user access token with `video.upload` and `video.publish` scopes.
"""

from clipper.publisher import ClipRecord, Publisher


class TikTokPublisher(Publisher):
    """Direct TikTok Video publisher stub."""

    def __init__(self, client_key: str = "", client_secret: str = ""):
        self.client_key = client_key
        self.client_secret = client_secret

    def check_token(self) -> bool:
        """Verify TikTok OAuth 2.0 access token validity."""
        # TODO: Implement token refresh and validation call
        return False

    def post(self, clip: ClipRecord, dry_run: bool = False) -> str:
        """Upload video to TikTok via Content Posting API.

        Raises:
            NotImplementedError: Direct TikTok publisher is a stub. Use UploadPostPublisher instead.
        """
        raise NotImplementedError(
            "Direct TikTok publishing via TikTok Content Posting API is not yet implemented.\n"
            "To publish to TikTok:\n"
            "  1. Use 'upload_post' publisher via Upload-Post relay (recommended), OR\n"
            "  2. Complete TikTok developer verification and call POST /v2/post/publish/video/init/.\n"
            "Reference: https://developers.tiktok.com/doc/content-posting-api-get-started"
        )
