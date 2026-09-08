"""The embedding port and its gateway adapter.

The reference layer holds a VIRTUAL KEY and nothing else: embeddings go through the gateway like
every other model call, so the upstream credential lives where `OLLAMA_API_KEY` already does. That
is what keeps "which embedding upstream" a configuration question rather than a code one.

The rules worth testing are all about not mis-attributing a vector. An embedding batch is
positional — the caller zips the vectors back onto its own rows — so a response that is short, long,
reordered or of the wrong dimension must refuse rather than be zipped.
"""
import json

import pytest

from lab.platform.embed import EmbedError, Embedder, GatewayEmbedder


class FakeHttp:
    """Stands in for the one JSON POST. Records what was sent, replies with what it was given."""

    def __init__(self, reply=None, dim=4):
        self.dim, self.calls = dim, []
        self._reply = reply

    def __call__(self, url, payload, headers=None, timeout=None):
        self.calls.append({"url": url, "payload": payload, "headers": headers or {}})
        if self._reply is not None:
            return json.dumps(self._reply) if not isinstance(self._reply, str) else self._reply
        vectors = [[float(i)] * self.dim for i, _ in enumerate(payload["input"])]
        return json.dumps({"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})


def embedder(http, **kw):
    return GatewayEmbedder(base_url="http://gw:4000", credential="sk-lab-1",
                           model="cohere.embed-v4.0", dim=4, http=http, **kw)


# ---------------------------------------------------------------- the port

def test_the_gateway_adapter_satisfies_the_port():
    assert isinstance(embedder(FakeHttp()), Embedder)


def test_it_declares_the_model_and_dimension_it_produces():
    """Both travel onto every indexed passage, so a query embedded by a different model or width
    is detectable instead of being silently cosine-compared."""
    e = embedder(FakeHttp())
    assert e.model == "cohere.embed-v4.0"
    assert e.dim == 4


# ---------------------------------------------------------------- calling the gateway

def test_it_calls_the_gateway_not_an_upstream():
    http = FakeHttp()
    embedder(http).embed(["a"], purpose="document")
    assert http.calls[0]["url"] == "http://gw:4000/v1/embeddings"


def test_it_authenticates_with_the_virtual_key():
    http = FakeHttp()
    embedder(http).embed(["a"], purpose="document")
    assert http.calls[0]["headers"]["Authorization"] == "Bearer sk-lab-1"


def test_a_document_and_a_query_are_embedded_differently():
    """Asymmetric embedding models want to know which side they are on; sending both as the same
    kind quietly costs recall that looks like a bad corpus."""
    http = FakeHttp()
    e = embedder(http)
    e.embed(["a"], purpose="document")
    e.embed(["a"], purpose="query")
    assert http.calls[0]["payload"]["input_type"] != http.calls[1]["payload"]["input_type"]


def test_an_unknown_purpose_refuses():
    with pytest.raises(EmbedError):
        embedder(FakeHttp()).embed(["a"], purpose="vibes")


def test_a_long_batch_is_split_and_every_vector_comes_back_in_order():
    http = FakeHttp()
    e = embedder(http, batch_size=2)
    out = e.embed([f"t{i}" for i in range(5)], purpose="document")
    assert len(out) == 5
    assert len(http.calls) == 3
    assert [c["payload"]["input"] for c in http.calls] == [["t0", "t1"], ["t2", "t3"], ["t4"]]


def test_embedding_nothing_calls_nothing():
    http = FakeHttp()
    assert embedder(http).embed([], purpose="document") == []
    assert http.calls == []


# ---------------------------------------------------------------- refusing to mis-attribute

def test_a_short_response_refuses_rather_than_zipping_what_it_got():
    """The failure this exists for. Silently zipping 2 vectors onto 3 rows attaches row 3's text
    to nothing and rows 1-2 to the wrong vectors — invisible until retrieval is quietly wrong."""
    http = FakeHttp(reply={"data": [{"index": 0, "embedding": [0.0] * 4}]})
    with pytest.raises(EmbedError) as e:
        embedder(http).embed(["a", "b", "c"], purpose="document")
    assert "3" in str(e.value) and "1" in str(e.value)


def test_a_vector_of_the_wrong_width_refuses():
    http = FakeHttp(reply={"data": [{"index": 0, "embedding": [0.0] * 9}]})
    with pytest.raises(EmbedError) as e:
        embedder(http).embed(["a"], purpose="document")
    assert "9" in str(e.value)


def test_vectors_are_ordered_by_the_index_the_provider_returns():
    """Providers are allowed to answer out of order. Trusting arrival order would transpose them."""
    http = FakeHttp(reply={"data": [{"index": 1, "embedding": [1.0] * 4},
                                    {"index": 0, "embedding": [0.0] * 4}]})
    out = embedder(http).embed(["first", "second"], purpose="document")
    assert out[0][0] == 0.0 and out[1][0] == 1.0


def test_a_response_that_is_not_embeddings_refuses():
    http = FakeHttp(reply={"error": {"message": "no such model"}})
    with pytest.raises(EmbedError) as e:
        embedder(http).embed(["a"], purpose="document")
    assert "no such model" in str(e.value)


def test_unparsable_json_refuses_with_what_came_back():
    http = FakeHttp(reply="<html>502 Bad Gateway</html>")
    with pytest.raises(EmbedError) as e:
        embedder(http).embed(["a"], purpose="document")
    assert "502" in str(e.value)


def test_a_duplicate_index_refuses_rather_than_last_one_winning():
    http = FakeHttp(reply={"data": [{"index": 0, "embedding": [0.0] * 4},
                                    {"index": 0, "embedding": [1.0] * 4}]})
    with pytest.raises(EmbedError):
        embedder(http).embed(["a", "b"], purpose="document")
