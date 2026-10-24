"""Upload local input files -> art:// refs — the command-line counterpart of the review app's Submit
page, and like it a CLIENT of the seam: files go through the gateway's `/api/uploads` (forwarded to
storage-mcp, which holds the store credentials) as the review app's own identity. Nothing here opens
a store, so running it needs the gateway and the app's Entra credential, not a bucket key.

    python -m lab.substrate.review.uploads upload <diagram|doc> ...
"""
import os
import sys

from lab.platform.filetypes import content_type_for
from lab.substrate.review import api


def upload(paths, *, client=None) -> list[str]:
    """Store local files in the UPLOAD store; returns their art:// refs (what a run is given).
    The original filename is kept: workloads decide how to read an input from its suffix."""
    client = client or api.from_config()
    out = []
    for p in paths:
        with open(p, "rb") as f:
            out.append(client.upload(os.path.basename(p), f.read(), content_type_for(p)))
    return out


def main(argv=None, *, client=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) > 1 and argv[0] == "upload":
        for p, ref in zip(argv[1:], upload(argv[1:], client=client)):
            print(f"{ref}\t{p}")
    else:
        sys.exit("usage: python -m lab.substrate.review.uploads upload <diagram|doc> ...")


if __name__ == "__main__":
    main()
