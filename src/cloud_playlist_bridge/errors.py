class BridgeError(Exception):
    """Base class for expected, user-facing failures."""


class InputError(BridgeError):
    """The supplied command input is invalid."""


class RemoteApiError(BridgeError):
    """A remote API returned an unusable response."""


class SourceIncompleteError(BridgeError):
    """The source playlist cannot be proven complete."""


class AuthenticationError(BridgeError):
    """Spotify authorization failed."""


class PartialMigrationError(BridgeError):
    """Spotify was changed, but the migration did not finish."""

    def __init__(self, message: str, *, playlist_url: str, added_count: int) -> None:
        super().__init__(message)
        self.playlist_url = playlist_url
        self.added_count = added_count


class QuotaExceededError(RemoteApiError):
    """Spotify's account-level development quota is exhausted."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class JobMismatchError(BridgeError):
    """A durable job does not belong to the current source snapshot or policy."""


class UncertainMigrationError(BridgeError):
    """Remote playlist state cannot be reconciled safely."""
