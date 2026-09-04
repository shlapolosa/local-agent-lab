"""Upload local input files into the UPLOAD store -> art:// refs — the local-dev counterpart of the
review app's Submit page. Substrate side on purpose: a workload never holds store credentials; its
inputs arrive as refs and are read through the gateway's storage-mcp.

    python -m lab.substrate.review.uploads upload <diagram|doc> ...
"""
import sys

from lab.substrate import artifacts


def upload(paths) -> list[str]:
    """Store local files in the UPLOAD store; returns their art:// refs (what a run is given)."""
    return [artifacts.put_file(p, content_type=artifacts.content_type_for(p), target=artifacts.uploads())
            for p in paths]


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) > 1 and argv[0] == "upload":
        for p, ref in zip(argv[1:], upload(argv[1:])):
            print(f"{ref}\t{p}")
    else:
        sys.exit("usage: python -m lab.substrate.review.uploads upload <diagram|doc> ...")


if __name__ == "__main__":
    main()
