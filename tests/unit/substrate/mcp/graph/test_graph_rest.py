"""src/lab/substrate/mcp/graph/graph_rest.py — transport only: bearer, paging, throttling, redirects
and streaming. It knows HTTP and Microsoft Graph's envelope; it knows nothing about capabilities or
domain objects, so every failure leaves here as a `GraphError` for the repository to explain.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_graph_rest.py"""
import email.message
import email.utils
import io
import urllib.error
import urllib.request

import pytest

from fixtures.graph import FakeSleep, FakeTokens, FakeTransport
from lab.substrate.mcp.graph import graph_rest

BASE = "https://graph.microsoft.com/v1.0"


def client(transport=None, sleep=None, **kw):
    return graph_rest.GraphClient(kw.pop("tokens", None) or FakeTokens("tok"),
                                  transport=transport or FakeTransport(), sleep=sleep or FakeSleep(), **kw)


# ------------------------------------------------------------------ the request
def test_a_get_reaches_graph_with_the_bearer_token_the_source_minted():
    t = FakeTransport().expect("/sites/root", body={"id": "s1"})
    assert client(t).get("/sites/root") == {"id": "s1"}
    call = t.calls[0]
    assert call["url"] == f"{BASE}/sites/root" and call["method"] == "GET"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["headers"]["Accept"] == "application/json"


def test_query_parameters_are_encoded_so_a_filter_with_spaces_and_quotes_survives():
    t = FakeTransport().expect("/events", body={"value": []})
    client(t).get("/users/u/events", {"$filter": "start/dateTime ge '2026-01-01'", "$top": 5})
    url = t.urls[0]
    assert "%24filter=" in url and "%20ge%20" in url and "%24top=5" in url


def test_an_empty_response_body_is_an_empty_object_not_a_parse_error():
    t = FakeTransport().expect("/subscriptions/s1", status=204, method="DELETE")
    assert client(t).delete("/subscriptions/s1") == {}


def test_a_body_carrying_verb_sends_json_and_says_so():
    t = FakeTransport().expect("/subscriptions", method="POST", body={"id": "sub-1"})
    assert client(t).post("/subscriptions", {"resource": "/drives/d/root"})["id"] == "sub-1"
    call = t.calls[0]
    assert call["headers"]["Content-Type"] == "application/json"
    assert b'"resource"' in call["body"]


def test_patch_is_the_verb_a_renewal_uses():
    t = FakeTransport().expect("/subscriptions/s1", method="PATCH", body={"id": "s1"})
    assert client(t).patch("/subscriptions/s1", {"expirationDateTime": "2026-09-05T00:00:00Z"})["id"] == "s1"
    assert t.calls[0]["method"] == "PATCH"


def test_the_base_url_is_configuration_so_beta_or_a_sovereign_cloud_is_an_env_edit():
    t = FakeTransport().expect("/x", body={})
    client(t, base_url="https://graph.microsoft.us/beta").get("/x")
    assert t.urls[0] == "https://graph.microsoft.us/beta/x"


# ------------------------------------------------------------------ paging
def test_a_page_returns_its_items_and_the_next_link_as_an_opaque_cursor():
    t = FakeTransport().expect("/sites", body={"value": [{"id": "a"}, {"id": "b"}],
                                               "@odata.nextLink": f"{BASE}/sites?$skiptoken=X"})
    items, cursor = client(t).paged("/sites")
    assert [i["id"] for i in items] == ["a", "b"]
    assert cursor == f"{BASE}/sites?$skiptoken=X"


def test_the_last_page_has_no_cursor():
    t = FakeTransport().expect("/sites", body={"value": [{"id": "a"}]})
    assert client(t).paged("/sites")[1] is None


def test_a_cursor_is_followed_verbatim_and_the_original_path_is_not_re_sent():
    t = FakeTransport().expect("$skiptoken=X", body={"value": []})
    client(t).paged("/sites", {"search": "*"}, cursor=f"{BASE}/sites?$skiptoken=X")
    assert t.urls == [f"{BASE}/sites?$skiptoken=X"] and "search" not in t.urls[0]


def test_a_cursor_pointing_anywhere_but_graph_is_refused_because_a_cursor_is_a_url_a_caller_supplies():
    with pytest.raises(ValueError, match="cursor"):
        client().paged("/sites", cursor="https://evil.example/steal")


def test_a_page_size_is_clamped_through_the_domains_one_limit_policy():
    t = FakeTransport().expect("/sites", body={"value": []}, times=None)
    c = client(t)
    c.paged("/sites", limit=10_000)
    c.paged("/sites", limit=None)
    assert "%24top=200" in t.urls[0] and "%24top=50" in t.urls[1]


def test_a_response_that_is_a_single_object_rather_than_a_collection_pages_as_one_item():
    t = FakeTransport().expect("/sites/root", body={"id": "only"})
    items, cursor = client(t).paged("/sites/root")
    assert items == [{"id": "only"}] and cursor is None


# ------------------------------------------------------------------ throttling
def test_a_429_is_retried_after_exactly_the_pause_graph_asked_for():
    t = FakeTransport().expect("/sites", status=429, headers={"Retry-After": "7"})
    t.expect("/sites", body={"value": [{"id": "a"}]})
    sleep = FakeSleep()
    assert client(t, sleep).paged("/sites")[0] == [{"id": "a"}]
    assert sleep.calls == [7.0] and len(t.calls) == 2


def test_a_retry_after_given_as_an_http_date_is_converted_to_seconds():
    when = email.utils.formatdate(1000.0 + 12, usegmt=True)
    t = FakeTransport().expect("/sites", status=429, headers={"Retry-After": when})
    t.expect("/sites", body={"value": []})
    sleep = FakeSleep()
    client(t, sleep, now=lambda: 1000.0).paged("/sites")
    assert sleep.calls == [12.0]


def test_a_service_unavailable_backs_off_the_same_way_because_graph_uses_both():
    t = FakeTransport().expect("/sites", status=503, headers={"Retry-After": "1"})
    t.expect("/sites", body={"value": []})
    sleep = FakeSleep()
    client(t, sleep).paged("/sites")
    assert sleep.calls == [1.0]


def test_a_missing_retry_after_falls_back_to_a_growing_back_off():
    t = FakeTransport().expect("/sites", status=429, times=None)
    sleep = FakeSleep()
    with pytest.raises(graph_rest.GraphError):
        client(t, sleep, max_retries=3).get("/sites")
    assert sleep.calls == [1.0, 2.0, 4.0] and len(t.calls) == 4


def test_retrying_is_bounded_and_the_last_refusal_still_carries_the_providers_hint():
    t = FakeTransport().expect("/sites", status=429, headers={"Retry-After": "2"}, times=None)
    with pytest.raises(graph_rest.GraphError) as e:
        client(t, FakeSleep(), max_retries=1).get("/sites")
    assert e.value.status == 429 and e.value.retry_after == 2.0


def test_a_hostile_retry_after_cannot_hang_a_run():
    t = FakeTransport().expect("/sites", status=429, headers={"Retry-After": "99999"}, times=None)
    sleep = FakeSleep()
    with pytest.raises(graph_rest.GraphError):
        client(t, sleep, max_retries=1).get("/sites")
    assert sleep.calls == [graph_rest.MAX_RETRY_DELAY]


def test_an_unparseable_retry_after_is_ignored_rather_than_trusted():
    t = FakeTransport().expect("/sites", status=429, headers={"Retry-After": "soon"}, times=None)
    sleep = FakeSleep()
    with pytest.raises(graph_rest.GraphError):
        client(t, sleep, max_retries=1).get("/sites")
    assert sleep.calls == [1.0]


# ------------------------------------------------------------------ errors
def test_a_refusal_carries_the_status_the_code_and_the_message_graph_gave():
    t = FakeTransport().expect("/recordings", status=403, body={
        "error": {"code": "Forbidden", "message": "No application access policy found for this app"}})
    with pytest.raises(graph_rest.GraphError) as e:
        client(t).get("/recordings")
    assert e.value.status == 403 and e.value.code == "Forbidden"
    assert "application access policy" in e.value.message


def test_an_inner_error_code_survives_because_it_is_sometimes_the_only_real_diagnosis():
    t = FakeTransport().expect("/transcripts", status=403, body={"error": {
        "code": "Forbidden", "message": "denied",
        "innerError": {"code": "GraphAccessToTranscriptsDisabled"}}})
    with pytest.raises(graph_rest.GraphError) as e:
        client(t).get("/transcripts")
    assert e.value.inner_code == "GraphAccessToTranscriptsDisabled"
    assert "GraphAccessToTranscriptsDisabled" in e.value.detail


def test_an_error_body_that_is_not_json_still_names_the_status():
    t = FakeTransport().expect("/x", status=502, body="<html>bad gateway</html>")
    with pytest.raises(graph_rest.GraphError) as e:
        client(t, FakeSleep()).get("/x")
    assert e.value.status == 502 and "bad gateway" in e.value.message


def test_a_two_hundred_that_is_not_json_is_a_proxy_answering_and_says_so():
    """A gateway or corporate proxy in front of Graph answers HTML with a 200 — exactly what the
    ADOIT edge does. A JSONDecodeError at char 0 names nothing; this names the cause."""
    t = FakeTransport().expect("/sites", body="<html>blocked by proxy</html>")
    with pytest.raises(graph_rest.GraphError) as e:
        client(t).get("/sites")
    assert e.value.code == "NonJsonResponse" and "blocked by proxy" in e.value.message


def test_an_abandoned_retry_response_is_closed_rather_than_left_open():
    t = FakeTransport().expect("/sites", status=429, headers={"Retry-After": "1"})
    t.expect("/sites", body={"value": []})
    client(t, FakeSleep()).paged("/sites")
    assert t.bodies[0].closed and not t.bodies[1].closed


def test_a_graph_error_reads_as_one_line_in_a_log():
    err = graph_rest.GraphError(404, "itemNotFound", "no such item")
    assert str(err) == "Microsoft Graph 404 itemNotFound: no such item"


# ------------------------------------------------------------------ streaming content
def test_stream_hands_back_the_body_unread_with_its_type_and_size():
    t = FakeTransport().expect("/content", body=b"video-bytes",
                               headers={"Content-Type": "video/mp4", "Content-Length": "11"})
    content = client(t).stream("/drives/d/items/i/content")
    assert content.content_type == "video/mp4" and content.size == 11
    assert content.fileobj.read() == b"video-bytes"


def test_a_stream_of_unknown_length_is_allowed_because_graph_often_omits_it():
    t = FakeTransport().expect("/content", body=b"x")
    assert client(t).stream("/x/content").size == 0


def test_a_declared_size_travels_with_the_stream_so_the_caller_can_refuse_it():
    """The ceiling itself is the repository's call — only it knows WHICH capability was attempted,
    and so which one to report as unavailable."""
    t = FakeTransport().expect("/content", body=b"x", headers={"Content-Length": "999999"})
    assert client(t).stream("/x/content").size == 999999


def test_a_stream_that_fails_raises_the_refusal_rather_than_handing_back_an_error_page():
    t = FakeTransport().expect("/content", status=404, body={"error": {"code": "itemNotFound"}})
    with pytest.raises(graph_rest.GraphError):
        client(t).stream("/x/content")


# ------------------------------------------------------------------ the redirect that leaks a token
def test_the_redirect_handler_drops_the_authorization_header_on_the_hop():
    """Graph answers /content with a 302 to a PRE-AUTHENTICATED Azure Blob URL and documents that no
    Authorization header is needed there — but urllib's default handler forwards every header except
    the content ones, so the bearer would travel to a CDN. This is the one place that is fixed."""
    req = urllib.request.Request(f"{BASE}/drives/d/items/i/content",
                                 headers={"Authorization": "Bearer secret", "Accept": "application/json"})
    new = graph_rest.AuthStrippingRedirectHandler().redirect_request(
        req, io.BytesIO(), 302, "Found", email.message.Message(), "https://blob.core.windows.net/x?sig=y")
    assert not any(k.lower() == "authorization" for k in new.headers)
    assert not any(k.lower() == "authorization" for k in new.unredirected_hdrs)
    assert new.headers["Accept"] == "application/json"
    assert new.full_url.startswith("https://blob.core.windows.net/")


def test_the_redirect_handler_refuses_what_the_base_handler_refuses():
    """Stripping a header must not turn a redirect urllib rejects (a 307 on a POST) into one it
    follows — the base handler still decides, this only edits the headers it produced."""
    req = urllib.request.Request(f"{BASE}/x", headers={"Authorization": "Bearer s"}, data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError):
        graph_rest.AuthStrippingRedirectHandler().redirect_request(
            req, io.BytesIO(), 307, "Temporary Redirect", email.message.Message(), f"{BASE}/y")


# ------------------------------------------------------------------ the real transport, without a network
class FakeOpener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeHTTPResponse(io.BytesIO):
    status = 200

    def __init__(self, raw=b"{}"):
        super().__init__(raw)
        self.headers = {"Content-Type": "application/json"}


def test_the_urllib_transport_passes_method_headers_and_body_through():
    opener = FakeOpener(FakeHTTPResponse(b'{"id": "x"}'))
    resp = graph_rest.UrllibTransport(opener)("POST", f"{BASE}/x", {"Authorization": "Bearer t"}, b"{}", 5)
    assert resp.status == 200 and resp.body.read() == b'{"id": "x"}'
    sent = opener.requests[0]
    assert sent.get_method() == "POST" and sent.data == b"{}"
    assert sent.headers["Authorization"] == "Bearer t"


def test_the_urllib_transport_turns_an_http_error_into_a_response_so_one_seam_carries_both():
    err = urllib.error.HTTPError(f"{BASE}/x", 403, "Forbidden", email.message.Message(),
                                 io.BytesIO(b'{"error": {"code": "Forbidden"}}'))
    resp = graph_rest.UrllibTransport(FakeOpener(err))("GET", f"{BASE}/x", {}, None, 5)
    assert resp.status == 403 and b"Forbidden" in resp.body.read()


def test_the_default_opener_installs_the_auth_stripping_redirect_handler_and_only_that_one():
    """`build_opener` drops a default handler when a subclass of it is supplied — so the stock
    redirect handler, the one that would forward the bearer, is not in the chain at all."""
    handlers = [h for h in graph_rest.UrllibTransport().opener.handlers
                if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert len(handlers) == 1 and isinstance(handlers[0], graph_rest.AuthStrippingRedirectHandler)


def test_a_client_built_without_a_transport_uses_the_real_one():
    assert isinstance(graph_rest.GraphClient(FakeTokens()).transport, graph_rest.UrllibTransport)


def test_a_content_length_that_cannot_be_read_is_treated_as_unknown_not_as_a_crash():
    """After the redirect the response comes from a CDN, not from Graph — its headers are not ours
    to trust, and the store enforces the real ceiling mid-stream anyway."""
    t = FakeTransport().expect("/content", body=b"x", headers={"Content-Length": "chunked"})
    assert client(t).stream("/x/content").size == 0


def test_a_provider_that_cannot_be_REACHED_is_a_graph_error_not_a_urllib_traceback():
    """DNS failure, connection refused, TLS, an outbound proxy, a read timeout: all of them are
    `URLError`/`OSError`, none of them is an `HTTPError`, and every one is likelier in a real
    deployment than a 403. They must leave here in the ONE shape the repository explains, or an
    agent relays `<urlopen error [Errno 61]>` to a human."""
    class Refusing:
        def open(self, req, timeout=None):
            raise urllib.error.URLError(OSError(61, "Connection refused"))

    transport = graph_rest.UrllibTransport(opener=Refusing())
    with pytest.raises(graph_rest.GraphError) as e:
        transport("GET", f"{BASE}/sites/root", {"Authorization": "Bearer tok"})
    assert e.value.status == 0 and e.value.code == "Unreachable"
    assert "could not be reached" in e.value.message and "Connection refused" in e.value.message


def test_a_bare_socket_error_is_caught_the_same_way():
    class Broken:
        def open(self, req, timeout=None):
            raise TimeoutError("timed out")

    with pytest.raises(graph_rest.GraphError) as e:
        graph_rest.UrllibTransport(opener=Broken())("GET", BASE, {})
    assert e.value.status == 0 and "timed out" in e.value.message
