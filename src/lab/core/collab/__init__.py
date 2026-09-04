"""The COLLABORATION bounded context: files and meetings, as the domain needs them.

One import for the whole port — the value objects (`model`), the typed refusals (`errors`) and the
`CollabRepository` Protocol (`port`). Pure domain: it names no provider and imports nothing outside
itself, so an adapter for any collaboration platform satisfies it and only the composition root
learns which one is wired.
"""
from lab.core.collab.errors import (CollabError, CollabNotConfigured, CollabThrottled,
                                    CollabUnavailable)
from lab.core.collab.model import (DEFAULT_LIMIT, MAX_LIMIT, ChangeType, ContentHandle,
                                   ContentStream, Drive, DriveItem, HandleKind, MediaKind,
                                   MediaRecord, Meeting, Page, Site, Watch, clamp_limit)
from lab.core.collab.port import CAPABILITIES, CollabRepository

__all__ = ["CollabRepository", "CAPABILITIES",
           "ContentHandle", "ContentStream", "HandleKind", "Site", "Drive", "DriveItem", "Meeting", "MediaKind",
           "MediaRecord", "ChangeType", "Watch", "Page", "clamp_limit", "DEFAULT_LIMIT", "MAX_LIMIT",
           "CollabError", "CollabUnavailable", "CollabNotConfigured", "CollabThrottled"]
