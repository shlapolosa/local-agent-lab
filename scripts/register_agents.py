"""Publish every agent's A2A card to the configured registry. Idempotent; safe to run on every push.

    set -a && source .env && set +a
    .venv/bin/python scripts/register_agents.py [--dry-run] [--public]

This is the third leg of the lab's identity claim. A virtual key says what an agent may spend and
reach; an Entra app registration says who it IS to the tenant; the card is what makes either
discoverable to anyone who did not write the code. The first two have existed for months and the
third never did — `GET /v1/agents` returned an empty list.

WHY A SCRIPT AND NOT A STARTUP HOOK. `POST /v1/agents` is an admin write: an agent's own virtual key
gets `403 "Only proxy admins can create, update, or delete agents"`. Self-registration would mean
handing every workload the master key, and an agent that can register agents can register a more
privileged one. So publication runs where the master key already lives — a person's shell, or CI.

WHY IT RECONCILES RATHER THAN CREATES. It runs on every push. "Declared once at creation and never
reconciled" is the defect the image tag had: a table is only the truth if something applies it every
time.

Stdlib only and `sys.path`-based, not an installed package: the CD deploy job installs nothing, the
same reason `deploy/railway.py` is stdlib-only.

Reads `PUBLIC_GATEWAY_URL` — NOT `GATEWAY_URL`, which defaults to 127.0.0.1 and would make a CI run
silently publish nothing to a gateway that is not there.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from lab.platform import config                                    # noqa: E402
from lab.platform.contracts import AGENTS                          # noqa: E402
from lab.substrate import agentregistry                            # noqa: E402


def _identity(prefix: str) -> tuple[str, str]:
    """This agent's virtual key and Entra client id, or empty strings.

    The same `<PREFIX>_KEY` / `<PREFIX>_CLIENT_ID` stems `lab.workloads.identity.agent_headers`
    reads, so a card can never claim an identity the run does not authenticate with. The SECRET is
    deliberately not read: nothing here needs it, and a value never loaded cannot be logged.
    """
    return os.environ.get(f"{prefix}_KEY", ""), os.environ.get(f"{prefix}_CLIENT_ID", "")


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    public = "--public" in argv
    gateway = config.PUBLIC_GATEWAY_URL or config.GATEWAY_URL
    if not dry and "127.0.0.1" in gateway:
        print("refusing: PUBLIC_GATEWAY_URL is unset, so this would publish to localhost. Set it, "
              "or pass --dry-run.", file=sys.stderr)
        return 2

    pub = (agentregistry.NullPublisher() if dry
           else agentregistry.publisher(public=public, client_to_key=config.ENTRA_CLIENT_TO_KEY))
    print(f"registry={config.AGENT_REGISTRY or 'none'} gateway={gateway} "
          f"agents={len(AGENTS)}{' (dry run)' if dry else ''}{' public' if public else ''}")

    published, skipped, failed = [], [], []
    for spec in AGENTS:
        key, client_id = _identity(spec.prefix)
        if not key and not client_id:
            # Ten of these identities are provisioned only when an operator runs the script against
            # a live tenant. A deployment where that has not happened must not fail here — it has
            # nothing to publish for that agent, which is a different thing from an error.
            skipped.append(spec.prefix)
            continue
        card = spec.card(gateway, config.ENTRA_TENANT_ID, config.ENTRA_GATEWAY_AUDIENCE,
                         client_id=client_id)
        try:
            pub.publish(spec, card, key=key, client_id=client_id)
            published.append(spec.name)
        except Exception as e:                    # noqa: BLE001 — one bad agent must not hide the rest
            failed.append(f"{spec.name}: {type(e).__name__}: {e}")

    print(f"published {len(published)}: {', '.join(published) or '-'}")
    if skipped:
        print(f"skipped {len(skipped)} with no credential yet: {', '.join(sorted(skipped))}")
    for line in failed:
        print(f"FAILED {line}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
