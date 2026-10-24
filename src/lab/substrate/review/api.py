"""The review app's client of the seam: `/api` for the gate, runs, uploads and artifacts, and gateway
MCP for the corpus. Nothing here holds a Redis, store or database credential (TO-BE, 24 Oct 2026).

WHY. The review app used to call `approvals`, `workflows`, `runlog` and the artifact store
in-process, which made it a peer of the service layer rather than a client of it: no low-code
surface could replace it, because no low-code surface could do what it did. Every call below is an
operation in `lab.substrate.apipolicy`, so a Power Apps page or a Teams tab can do exactly what this
app does, holding exactly the same roles.

IDENTITY — the app relays its person. It authenticates as ITSELF (client credentials on its own Entra
registration, `REVIEW_ENTRA_CLIENT_ID`, holding Workflow.Submit + Approvals.Read + Approvals.Decide)
and passes the signed-in reviewer as `actor` / `requester` — the RELAY pattern (user decision 24 Oct
2026). That app credential is REQUIRED: `/api` refuses a virtual key, so there is no key fallback. The
PERSON may still sign in through the password gate when SSO is not configured; only the app's own
credential is mandatory.

ERRORS keep the shapes the pages already handle: a missing thing is `KeyError` (or `{}` for a status
read), a refusal a person can read is `ValueError` carrying the door's own sentence.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from typing import Any

import httpx

from lab.platform.contracts import ReferenceTools

__all__ = ["LabApi", "CHANNEL", "PREFIX", "from_config"]

#: How the gate records a decision taken here: `api:review-app` — the door stamps the `api:` prefix.
CHANNEL = "review-app"

#: The env prefix of the app's own Entra registration: REVIEW_ENTRA_CLIENT_ID / _SECRET.
PREFIX = "REVIEW_ENTRA"

McpCall = Callable[[list], Coroutine[Any, Any, list]]


class LabApi:
    """`base_url` is the gateway's `/api`; `headers` returns the app's credential (fresh per call, so
    an MSAL token refreshes itself); `mcp` calls gateway MCP tools by suffix as the same identity."""

    def __init__(self, base_url: str, headers: Callable[[], Mapping[str, str]], *,
                 mcp: McpCall | None, transport: httpx.BaseTransport | None = None,
                 timeout: float = 60):
        self.base = base_url.rstrip("/")
        self._headers, self._mcp = headers, mcp
        self._transport, self._timeout = transport, timeout
        self._client: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        """Built on first use, so constructing the client at import opens nothing."""
        if self._client is None:
            self._client = httpx.Client(transport=self._transport, timeout=self._timeout)
        return self._client

    # ---------------------------------------------------------------- plumbing
    def _call(self, method: str, path: str, **kw) -> httpx.Response:
        return self._http.request(method, self.base + path, headers=dict(self._headers()), **kw)

    @staticmethod
    def _refusal(got: httpx.Response) -> str:
        try:
            return str(got.json().get("error") or got.text)
        except ValueError:
            return got.text

    def _json(self, method: str, path: str, *, missing: Any = KeyError, **kw) -> Any:
        got = self._call(method, path, **kw)
        if got.status_code == 404:
            if missing is KeyError:
                raise KeyError(self._refusal(got))
            return missing
        if got.status_code in (400, 409, 422):
            raise ValueError(self._refusal(got))
        got.raise_for_status()
        return got.json()

    # ---------------------------------------------------------------- artifacts and uploads
    def artifact(self, ref: str) -> bytes:
        got = self._call("GET", "/artifacts", params={"ref": ref})
        if got.status_code in (400, 404):
            raise KeyError(f"no artifact {ref}")
        got.raise_for_status()
        return got.content

    def upload(self, name: str, data: bytes, content_type: str) -> str:
        return self._json("POST", "/uploads", files=[("files", (name, data, content_type))])["refs"][0]

    # ---------------------------------------------------------------- the approval gate
    def pending(self) -> list[dict]:
        """Every open approval IN FULL (payload included), in one call."""
        return self._json("GET", "/approvals", params={"full": 1})["approvals"]

    def status(self, approval_id: str) -> dict:
        return self._json("GET", f"/approvals/{approval_id}", missing={})

    def history(self, limit: int = 20) -> list[dict]:
        return self._json("GET", "/approvals", params={"history": limit})["history"]

    def decide(self, approval_id: str, decision: str, actor: str, comment: str = "", *,
               answer: Any = None) -> dict:
        body = {"decision": decision, "actor": actor, "comment": comment, "channel": CHANNEL}
        if answer is not None:
            body["answer"] = answer
        return self._json("POST", f"/approvals/{approval_id}/decide", json=body)

    # ---------------------------------------------------------------- runs and submissions
    def submit(self, process: str, inputs: Mapping[str, Any], requester: str) -> str:
        return self._json("POST", f"/processes/{process}/runs",
                          json={**inputs, "requester": requester})["request_id"]

    def request_status(self, request_id: str) -> dict:
        return self._json("GET", f"/requests/{request_id}", missing={})

    def recent_requests(self, limit: int = 10) -> list[dict]:
        return self._json("GET", "/requests", params={"limit": limit})["requests"]

    def board(self, limit: int = 20) -> tuple[list[dict], list[dict]]:
        got = self._json("GET", "/board", params={"limit": limit})
        return got["active"], got["recent"]

    def run(self, run_id: str) -> dict:
        return self._json("GET", f"/board/{run_id}", missing={})

    # ---------------------------------------------------------------- the corpus, through gateway MCP
    def corpus_records(self, artifact: str, record_type: str, *, field: str) -> list[dict]:
        """Every record of one whole-retrieval artifact, read under a fresh pin and attributed to
        `field` in the consumption trail — the same read the review app made in-process."""
        if self._mcp is None:
            raise RuntimeError("no gateway MCP transport configured")
        (pin,) = asyncio.run(self._mcp([(ReferenceTools.pin, {"artifact_ids": [artifact]})]))
        (out,) = asyncio.run(self._mcp([(ReferenceTools.lookup, {
            "pin_id": pin["pin_id"], "record_type": record_type, "key": {}, "run_id": CHANNEL,
            "process": CHANNEL, "field": field, "artifact_id": artifact})]))
        return [dict(r.get("body") or {}) for r in (out or {}).get("records") or []]


def from_config() -> LabApi:
    """The client the running app uses: the gateway's `/api`, the app's own Entra token, and gateway
    MCP as the same identity. The gateway maps the token to the app's virtual key (`REVIEW_APP_KEY`
    in ENTRA_CLIENT_TO_KEY), which is what meters it and carries its one MCP grant."""
    from lab.platform import config, credential, identity, mcp_client

    def headers() -> Mapping[str, str]:
        token = identity.agent_token(PREFIX)
        if not token:
            raise RuntimeError(f"the review app reaches the lab through /api and needs its own Entra "
                               f"registration: set {PREFIX}_CLIENT_ID and {PREFIX}_CLIENT_SECRET "
                               "(scripts/provision_review_app_identity.py grants it the roles)")
        return credential.headers(token)

    async def mcp(calls: list) -> list:
        return await mcp_client.call_tools(headers(), config.GATEWAY_MCP_URL, calls)

    return LabApi(config.GATEWAY_URL.rstrip("/") + "/api", headers, mcp=mcp)
