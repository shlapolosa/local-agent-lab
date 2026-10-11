"""The one normaliser for a provider WEB URL — the address a person copies out of a browser.

`DriveItem.url` is the third way of naming one file (a handle addresses bytes for a tool, an id
addresses a write, a url is the only one a HUMAN can use), and retrieval hands an assistant exactly
that: `https://<tenant>/sites/<site>/Shared%20Documents/BRS.md`. Resolving one to custody needs the
same url to be ONE url however it was copied, which is what this does.

It is deliberately a SMALL normalisation, because the failure modes are not symmetrical. Two shapes
of one document that fail to agree cost one extra provider call and a "not catalogued" answer a
reader can see is wrong. Two DIFFERENT documents folded onto one url cost a confident answer about
the wrong record — the silent failure the whole custody lookup exists to avoid. So:

  * the SCHEME and HOST are lower-cased (DNS is case-insensitive, and so is a URL scheme);
  * the FRAGMENT goes (`#heading-2` is where a reader was, not which file it is);
  * the QUERY goes when it is view state (`?web=1`, `?csf=1&e=…` — what "Copy link" and the Office
    viewer append), and is KEPT whole when it names the item: a classic library view carries the
    file's own server-relative path in `?id=` and a Word document can be addressed by
    `?sourcedoc=<guid>`, so dropping that turns the address of one document into the address of the
    whole library — a different thing that still resolves, which is the worst outcome available;
  * a trailing slash goes;
  * the PATH is untouched — neither its case nor its percent-encoding. `Shared Documents` and
    `Shared%20Documents` mean the same folder to today's provider but are not the same bytes, and
    re-encoding either way would be this module guessing on a provider's behalf.

Pure, so it is tested on its own and both ends of the lookup share one answer.
"""
from __future__ import annotations

import urllib.parse

__all__ = ["normalise_web_url", "IDENTIFYING_PARAMS"]

#: Query parameters that name WHICH item, rather than how it is being viewed. A query carrying any of
#: them is kept verbatim.
IDENTIFYING_PARAMS = ("id", "sourcedoc")


def normalise_web_url(url: str) -> str:
    """One canonical form of a web URL. `ValueError` for anything that is not an absolute http(s)
    URL — a `collab://` handle, a bare path or an empty string is a caller error worth surfacing,
    not something to resolve against a provider and be told nothing about."""
    text = str(url or "").strip()
    parts = urllib.parse.urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(f"not an absolute web url: {url!r}")
    names_item = any(k.lower() in IDENTIFYING_PARAMS
                     for k, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query = parts.query if names_item else ""
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                                    parts.path.rstrip("/"), query, ""))
