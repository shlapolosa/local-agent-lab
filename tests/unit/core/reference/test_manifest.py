"""The signed manifest — what DR-01's "version identifier and a signature" actually is here.

The signature covers BOTH forms of the artifact and the exact derived content, because DR-02's
invariant is that they are the same artifact at the same version. Signing only the master would
leave the agent-readable form editable in the database with nothing to detect it, which is the one
thing this layer exists to prevent.
"""
import pytest

from lab.core.reference.manifest import (
    ManifestError,
    canonical,
    generate_key,
    manifest,
    sign,
    verify,
)

FIELDS = dict(artifact_id="guardrails", version="2026.09.1", kind="record",
              master_sha256="a" * 64, agent_sha256="b" * 64, derived_from="a" * 64,
              content_digest="c" * 64, published_at="2026-09-08T00:00:00Z", key_id="k1")


# ---------------------------------------------------------------- canonical form

def test_the_canonical_form_is_stable_whatever_order_the_fields_arrive_in():
    a = canonical({"b": 2, "a": 1})
    b = canonical({"a": 1, "b": 2})
    assert a == b


def test_the_canonical_form_carries_no_incidental_whitespace():
    assert " " not in canonical({"a": 1, "b": "x"})


def test_a_manifest_refuses_to_omit_a_field_the_signature_is_supposed_to_cover():
    with pytest.raises(ManifestError) as e:
        manifest(**{k: v for k, v in FIELDS.items() if k != "agent_sha256"})
    assert "agent_sha256" in str(e.value)


def test_a_manifest_whose_derived_form_does_not_come_from_its_master_is_refused():
    """DR-02 as a refusal rather than a hope: a version cannot claim a master it was not derived
    from, and the manifest is where that becomes unforgeable."""
    with pytest.raises(ManifestError) as e:
        manifest(**FIELDS | {"derived_from": "d" * 64})
    assert "derived_from" in str(e.value)


# ---------------------------------------------------------------- sign and verify

def test_a_signature_verifies_against_its_own_manifest():
    private, public = generate_key()
    body = manifest(**FIELDS)
    assert verify(body, sign(body, private), public) is True


def test_a_signature_does_not_verify_against_a_different_key():
    private, _ = generate_key()
    _, other_public = generate_key()
    body = manifest(**FIELDS)
    assert verify(body, sign(body, private), other_public) is False


def test_editing_the_agent_readable_form_breaks_the_signature():
    """The property that matters operationally: a row edited in the database, with no re-publish,
    is detectable at the next pin."""
    private, public = generate_key()
    signature = sign(manifest(**FIELDS), private)
    tampered = manifest(**FIELDS | {"agent_sha256": "e" * 64, "content_digest": "f" * 64})
    assert verify(tampered, signature, public) is False


def test_a_changed_version_string_breaks_the_signature():
    private, public = generate_key()
    signature = sign(manifest(**FIELDS), private)
    assert verify(manifest(**FIELDS | {"version": "2026.09.2"}), signature, public) is False


def test_a_malformed_signature_is_false_rather_than_an_exception():
    """Verification runs at every pin. A corrupt signature is a refusal to serve the artifact, not
    a crash in the caller."""
    _, public = generate_key()
    assert verify(manifest(**FIELDS), "not-a-signature", public) is False


def test_a_malformed_public_key_is_refused_loudly():
    """A key we cannot read is an operator error, not an untrusted artifact — the difference
    matters, because one is fixed by re-publishing and the other by fixing the trust store."""
    with pytest.raises(ManifestError):
        verify(manifest(**FIELDS), "AAAA", "not-a-key")


def test_the_manifest_names_the_key_that_signed_it():
    body = manifest(**FIELDS)
    assert '"key_id":"k1"' in body
