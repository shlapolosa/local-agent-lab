"""Write the front door's OpenAPI (Swagger 2.0) document — the file a custom connector is imported from.

    python scripts/render_openapi.py <gateway base url> <out.json>

GENERATED, not templated: the document is derived from the process registry and the gateway's `/api`
operation table (`lab.platform.openapi`), so it is rendered by code rather than by `sed` over
a committed template. Run by `./lab.sh clients`; the output is git-ignored like every rendered client.
"""
import json
import sys

from lab.platform.openapi import openapi
from lab.substrate import apipolicy


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    base_url, out = argv
    with open(out, "w", encoding="utf-8") as f:
        json.dump(openapi(base_url, apipolicy.OPERATIONS), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
