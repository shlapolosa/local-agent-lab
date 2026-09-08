"""The signed manifest of an artifact version — DR-01's "version identifier and a signature".

**What "signed" honestly means here, stated so nobody reads more into it than it carries:**
integrity and authorship-by-key-possession. It is NOT identity, NOT non-repudiation, and NOT
revocation by a certificate authority — this lab has no PKI, and pretending otherwise would be
worse than the plain claim. The trust anchor is the deploy profile, the same anchor as every other
lab secret, with one hard rule: **the private key must never live in `LAB_ENV`**, or a signature
proves only "somebody with repo admin", which is everybody who could have edited the row anyway.

What it does buy, and these are real:

* the agent-readable form cannot be edited in the database without detection, because the signature
  covers the derived CONTENT and not merely the master;
* a version cannot claim a master it was not derived from — DR-02 becomes unforgeable rather than
  a convention;
* `key_id` names who published.

On Azure the private key moves to Key Vault and the publisher calls `sign()` there. The manifest,
the fields it covers and the verification point are unchanged — which is the whole reason the
signing is a pure function over a canonical string and holds no key material of its own.
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

__all__ = ["MANIFEST_FIELDS", "ManifestError", "canonical", "generate_key", "manifest", "sign",
           "verify"]

#: Everything the signature covers. Both digests are in deliberately: signing only the master would
#: leave the agent-readable form editable with nothing to detect it.
MANIFEST_FIELDS = ("artifact_id", "version", "kind", "master_sha256", "agent_sha256",
                   "derived_from", "content_digest", "published_at", "key_id")


class ManifestError(ValueError):
    """The manifest could not be built, or the key material could not be read."""


def canonical(value: Mapping[str, Any]) -> str:
    """One byte-form per manifest, whatever order the fields were assembled in."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def manifest(**fields: Any) -> str:
    """The canonical manifest string, or a refusal naming what is missing or inconsistent."""
    missing = [f for f in MANIFEST_FIELDS if not str(fields.get(f, "")).strip()]
    if missing:
        raise ManifestError(f"a manifest must carry {list(MANIFEST_FIELDS)}; missing {missing}")
    extra = sorted(set(fields) - set(MANIFEST_FIELDS))
    if extra:
        raise ManifestError(f"a manifest carries exactly {list(MANIFEST_FIELDS)}; got extra {extra}"
                            f" — a field outside the signed set would not be covered by the "
                            f"signature and must not travel with it")
    if fields["derived_from"] != fields["master_sha256"]:
        raise ManifestError(
            "derived_from must equal master_sha256: the agent-readable form is derived from THIS "
            "master, and DR-02 makes divergence a defect rather than a lag")
    return canonical({f: fields[f] for f in MANIFEST_FIELDS})


def generate_key() -> tuple[str, str]:
    """A fresh (private seed, public key) pair, both base64. For tests and for bootstrapping."""
    private = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    seed = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption())
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return base64.b64encode(seed).decode(), base64.b64encode(public).decode()


def _decode(material: str, what: str) -> bytes:
    try:
        return base64.b64decode(material, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ManifestError(f"the {what} is not base64: {exc}") from exc


def sign(body: str, private_key: str) -> str:
    """Sign a canonical manifest with a base64 Ed25519 seed."""
    try:
        key = Ed25519PrivateKey.from_private_bytes(_decode(private_key, "private key"))
    except ValueError as exc:
        raise ManifestError(f"the private key is not an Ed25519 seed: {exc}") from exc
    return base64.b64encode(key.sign(body.encode("utf-8"))).decode()


def verify(body: str, signature: str, public_key: str) -> bool:
    """Does this signature cover this manifest under this key?

    A bad SIGNATURE is `False` — the artifact is not trustworthy, and verification runs at every
    pin, so it must be a refusal to serve rather than a crash in the caller. A bad KEY raises,
    because that is an operator error in the trust store: one is fixed by re-publishing, the other
    by fixing configuration, and collapsing them would send whoever is on call to the wrong place.
    """
    try:
        key = Ed25519PublicKey.from_public_bytes(_decode(public_key, "public key"))
    except ValueError as exc:
        raise ManifestError(f"the public key is not an Ed25519 key: {exc}") from exc
    try:
        key.verify(base64.b64decode(signature), body.encode("utf-8"))
    except (InvalidSignature, binascii.Error, ValueError):
        return False
    return True
