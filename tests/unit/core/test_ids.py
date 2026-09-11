"""ULIDs for the fabric's identifiers: 26 Crockford base32 characters, time-ordered, no dependency."""
import re
import time

from lab.core import ids

CROCKFORD = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_shape_is_26_crockford_characters():
    assert CROCKFORD.fullmatch(ids.ulid())


def test_is_valid_accepts_and_refuses():
    assert ids.is_ulid(ids.ulid())
    assert not ids.is_ulid("not-a-ulid")
    assert not ids.is_ulid("01J9X5K7QZ3M8N2P4R6T8V0W1I")   # I is not in the alphabet
    assert not ids.is_ulid("")


def test_time_ordered_and_unique():
    a = ids.ulid(ms=1_000)
    b = ids.ulid(ms=2_000)
    assert a < b, "the first ten characters encode the millisecond, so later sorts after"
    assert len({ids.ulid() for _ in range(500)}) == 500


def test_timestamp_round_trips():
    now = int(time.time() * 1000)
    assert ids.ulid_ms(ids.ulid(ms=now)) == now


def test_artifact_iri_scheme():
    iri = ids.artifact_iri()
    assert iri.startswith("urn:fabric:artifact:") and ids.is_ulid(iri.rsplit(":", 1)[1])
