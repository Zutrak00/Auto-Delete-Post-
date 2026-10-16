from .base import Field, Provider, ProviderError
from .bluesky import BlueskyProvider
from .facebook import FacebookPageProvider
from .mastodon import MastodonProvider
from .reddit import RedditProvider
from .threads import ThreadsProvider
from .tumblr import TumblrProvider
from .twitter import XProvider

PROVIDERS: dict[str, type[Provider]] = {
    p.key: p for p in (
        XProvider, BlueskyProvider, MastodonProvider, RedditProvider, ThreadsProvider,
        TumblrProvider, FacebookPageProvider,
    )
}

# Platforms people ask about whose official APIs don't let third-party apps delete posts.
UNSUPPORTED = {
    "Instagram": "Meta's API does not offer post deletion for personal accounts. Use the app's "
    "'Your activity → Posts' screen to bulk-delete or archive.",
    "Facebook (personal profile)": "Meta removed API access to personal profile posts (Pages are supported "
    "above). Use 'Activity log → Manage posts' to bulk-delete or set them to Only me.",
    "TikTok": "TikTok's API does not let apps delete videos. Delete or set them to private in the app.",
    "LinkedIn": "Listing your own posts needs a partner-only permission, so automatic cleanup isn't possible.",
}

__all__ = ["Field", "Provider", "ProviderError", "PROVIDERS", "UNSUPPORTED"]
