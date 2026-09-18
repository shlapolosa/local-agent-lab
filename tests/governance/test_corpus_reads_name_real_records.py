"""Every artifact a service reads names a record type the publisher actually publishes.

A `record_type` that does not match returns ZERO records and no error. The review app then reports
that the corpus could not be read — true, useless, and indistinguishable from an unpublished
artifact. Found exactly that way on 18 Sep 2026: the roadmap asked for `("process-steps", "step")`
when the publisher declares `process-step`, so a page that had been driven under real Streamlit
still showed nothing and blamed the corpus.

This is the same shape as the dangling guardrail bindings: a join whose failure mode is an empty
result needs a check that the operands exist, because an empty result is what success looks like
when the data is genuinely silent.
"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Where a service declares `(artifact_id, record_type)` pairs to read. Add a file when a new
#: consumer does the same; the pattern is a literal tuple, which is how they are all written.
READERS = ("src/lab/substrate/review/app.py",)


def _published() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location(
        "_pub", ROOT / "scripts" / "publish_usecase_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {artifact: entry[0] for artifact, entry in module.ARTIFACTS.items()}


def _pairs(rel: str) -> list[tuple[str, str]]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    return re.findall(r'\("([a-z0-9][a-z0-9-]+)",\s*"([a-z0-9][a-z0-9-]+)"\)', text)


def test_no_reader_asks_for_a_record_type_the_publisher_does_not_publish():
    published = _published()
    wrong = [f"{rel}: ({artifact!r}, {kind!r}) — published as {published[artifact]!r}"
             for rel in READERS for artifact, kind in _pairs(rel)
             if artifact in published and published[artifact] != kind]
    assert not wrong, ("a mismatched record type returns no records and no error, so the page "
                       f"reports an unreadable corpus instead of a typo: {wrong}")


def test_every_artifact_a_reader_names_is_one_the_publisher_knows():
    """The other direction. A reader naming an artifact nobody publishes is a feature that can
    never work, and it fails as silence rather than as a missing artifact."""
    published, known = _published(), set(_published())
    # Only pairs whose SECOND element is also a declared record type are artifact reads; the regex
    # otherwise matches any two-string tuple in the file.
    types = set(published.values())
    unknown = sorted({artifact for rel in READERS for artifact, kind in _pairs(rel)
                      if kind in types and artifact not in known})
    assert not unknown, f"read from the corpus but never published: {unknown}"
