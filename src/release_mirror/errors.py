from __future__ import annotations


class SyncError(RuntimeError):
    """Raised when the sync operation cannot continue safely."""
