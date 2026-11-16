"""YouTube Publisher stub for direct YouTube Data API v3 publishing.

Requirements and API Documentation:
- API: YouTube Data API v3 (Videos: insert)
- Docs: https://developers.google.com/youtube/v3/docs/videos/insert
- Required Credentials:
  - Google Cloud Project with YouTube Data API v3 enabled.
  - OAuth 2.0 Client ID and Secret (`client_secrets.json`).
  - Scopes: `https://www.googleapis.com/auth/youtube.upload`
  - Valid OAuth 2.0 refresh token for headless operation.
"""

from clipper.publisher import ClipRecord, Publisher


class YouTubePublisher(Publisher):
    """Direct YouTube Shorts publisher stub."""

    def __init__(self, client_secrets_file: str = "client_secrets.json"):
        self.client_secrets_file = client_secrets_file

    def check_token(self) -> bool:
        """Verify YouTube OAuth 2.0 access token validity."""
        # TODO: Implement token expiration check against Google OAuth token endpoint
        return False

    def post(self, clip: ClipRecord, dry_run: bool = False) -> str:
        """Upload video to YouTube Shorts using YouTube Data API v3.

        Raises:
            NotImplementedError: Direct YouTube publisher is a stub. Use UploadPostPublisher instead.
        """
        raise NotImplementedError(
            "Direct YouTube publishing via YouTube Data API v3 is not yet implemented.\n"
            "To publish to YouTube Shorts:\n"
            "  1. Use 'upload_post' publisher via Upload-Post relay (recommended), OR\n"
            "  2. Implement OAuth2 client_secrets.json authorization and Videos.insert multipart upload.\n"
            "Reference: https://developers.google.com/youtube/v3/docs/videos/insert"
        )
