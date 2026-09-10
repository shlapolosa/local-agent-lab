"""Reconcile the gateway's vector stores to `lab.platform.contracts.VectorStores`. Idempotent; a CD step.

    set -a && source .env && set +a
    .venv/bin/python scripts/register_vector_stores.py [--dry-run]

WHY THE DATABASE AND NOT THE YAML. A `vector_store_registry:` block in litellm-config.yaml loads
into memory at start — and with a database configured the database is the source of truth: the
list endpoint DELETES any in-memory store it does not find there. Verified live on 1.98: the block
loaded, one `GET /vector_store/list` later the registry held zero stores, and a search fell through
to OpenAI's own vector-store API. So a store is a registry object like a team or a key, written
where those are written and reconciled on every push, because a table is only the truth if
something applies it every time.

WHAT A STORE CARRIES. Its id (= the reference artifact id), the `pg_vector` provider, and a
description. NO credential and NO api_base: LiteLLM resolves no `os.environ/` on this path, so the
provider reads PG_VECTOR_API_BASE / PG_VECTOR_API_KEY from the gateway's own environment (set by
deploy/railway.py substrate_env and lab.sh) — a credential written into the store row would be one
more copy of MCP_SHARED_SECRET to rotate.

Stdlib only and `sys.path`-based, like `register_agents.py`: the CD deploy job installs nothing.
Reads `PUBLIC_GATEWAY_URL`, not `GATEWAY_URL` (which defaults to 127.0.0.1 in CI, where there is no
gateway). Waits for a gateway that is still booting after `substrate up`, because a redeployed
gateway answers 502 for a while and "not ready" is not "not registered".
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from lab.platform.contracts import VectorStores                    # noqa: E402

READY_TIMEOUT_S = 300


def _call(base: str, key: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _wait_ready(base: str, key: str) -> None:
    """A gateway redeployed moments ago answers 502 from the edge until it binds. Not an error —
    unless it lasts longer than a boot plausibly does."""
    deadline = time.time() + READY_TIMEOUT_S
    while True:
        try:
            _call(base, key, "GET", "/health/liveliness")
            return
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if time.time() > deadline:
                raise SystemExit(f"gateway not ready after {READY_TIMEOUT_S}s: {exc}")
            print(f"  gateway not ready ({exc}); retrying in 5s", flush=True)
            time.sleep(5)


def registered(base: str, key: str) -> dict[str, dict]:
    page = _call(base, key, "GET", "/vector_store/list?page_size=200")
    return {v["vector_store_id"]: v for v in page.get("data") or [] if v.get("vector_store_id")}


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    wanted = {store: {"vector_store_id": store, "custom_llm_provider": VectorStores.PROVIDER,
                      "vector_store_name": store,
                      "vector_store_description": VectorStores.DESCRIPTION.get(store, ""),
                      "litellm_params": {}}
              for store in sorted(VectorStores.names())}
    if dry:
        print(json.dumps(list(wanted.values()), indent=2))
        return 0
    base = os.environ.get("PUBLIC_GATEWAY_URL", "")
    key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not base or not key:
        raise SystemExit("PUBLIC_GATEWAY_URL and LITELLM_MASTER_KEY are required — source .env")

    _wait_ready(base, key)
    have = registered(base, key)
    created = 0
    for store, body in wanted.items():
        if store in have:
            provider = have[store].get("custom_llm_provider")
            if provider != VectorStores.PROVIDER:
                _call(base, key, "POST", "/vector_store/update",
                      {"vector_store_id": store, "custom_llm_provider": VectorStores.PROVIDER})
                print(f"  {store:44} provider {provider!r} -> {VectorStores.PROVIDER}")
            else:
                print(f"  {store:44} registered")
            continue
        _call(base, key, "POST", "/vector_store/new", body)
        created += 1
        print(f"  {store:44} created")

    # The instrument that can fail loudly: what the gateway LISTS for the master key is what a
    # workload's preflight will see. Anything short of the contract is a failed deploy, not a note.
    listed = set(registered(base, key))
    missing = sorted(set(wanted) - listed)
    if missing:
        print(f"FAILED: the gateway does not list {missing} after registration", file=sys.stderr)
        return 1
    print(f"{created} created, {len(wanted) - created} already registered; "
          f"{len(wanted)} stores match lab.platform.contracts.VectorStores")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
