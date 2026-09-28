"""Content from RESTRICTED or unclassified tenant sources never becomes a committed master.

This repository is PUBLIC. The CAFÉ bundle of 28 Sep 2026 carried tables taken from the ADHDS
Cyber Risk Management Framework v2.0 — marked RESTRICTED by the Information Security Office — and
from ADHDS documents whose classification is not stated (the Target State Architecture v1, an
Accenture deliverable; the ADHDS AI use-case catalogue). User decision, 28 Sep 2026: every table
sourced from either stays OUT of git and reaches the corpus by `art://` reference from the private
artifact store — the path the licensed BA Guild workbooks already take — until each source's
classification is confirmed.

A list of private ids is only as good as the next import that forgets it, so the tripwire reads
the CONTENT: a committed master that names one of these sources fails here whatever the list says.
"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corpus = _load("publish_usecase_corpus")
workbook = _load("artifacts_workbook")

#: What marks a master as sourced from a document this repository may not carry.
#: `RESTRICTED` is matched CASE-SENSITIVELY and the rest are not: in CAFÉ `restricted` is also a
#: sensitivity CLASS (public · internal · confidential · restricted), so the guardrails and the facet
#: schema say it legitimately. The document MARKING is the uppercase word.
RESTRICTED_SOURCE = re.compile(r"(?i:\bADHDS\b|\bCRMF\b|Cyber Risk Management Framework|"
                               r"Target State Architecture)|\bRESTRICTED\b")


def test_no_committed_master_names_a_restricted_or_unclassified_source():
    leaked = {p.name: RESTRICTED_SOURCE.search(p.read_text()).group(0)
              for p in corpus.MASTERS.glob("*.md") if RESTRICTED_SOURCE.search(p.read_text())}
    assert not leaked, (f"committed masters carry restricted-source content {leaked} — route "
                        f"the artifact through PRIVATE instead")


def test_no_private_artifact_has_a_committed_master():
    committed = {p.stem.replace("_", "-") for p in corpus.MASTERS.glob("*.md")}
    assert not committed & set(corpus.PRIVATE), sorted(committed & set(corpus.PRIVATE))


def test_a_private_master_is_written_OUTSIDE_the_repository():
    for artifact_id in corpus.PRIVATE:
        path = workbook.master_path(artifact_id)
        assert ROOT / "src" not in path.parents, f"{artifact_id} would be written to {path}"
        assert path == corpus.master_for(artifact_id), "importer and publisher disagree"


def test_every_private_artifact_says_WHY_it_is_private():
    """An unexplained entry is one somebody deletes to make a publish go through."""
    assert corpus.PRIVATE and all(reason.strip() for reason in corpus.PRIVATE.values())


def test_every_private_artifact_is_still_a_declared_artifact():
    assert set(corpus.PRIVATE) <= set(corpus.ARTIFACTS), sorted(set(corpus.PRIVATE) -
                                                                set(corpus.ARTIFACTS))


def test_the_private_refs_parse_as_a_list(monkeypatch):
    import importlib
    from lab.platform import config
    monkeypatch.setenv("REFERENCE_PRIVATE_MASTERS_REFS", " art://a/one.md , art://b/two.md ,")
    importlib.reload(config)
    try:
        assert config.REFERENCE_PRIVATE_MASTERS_REFS == ("art://a/one.md", "art://b/two.md")
        monkeypatch.delenv("REFERENCE_PRIVATE_MASTERS_REFS")
        importlib.reload(config)
        assert config.REFERENCE_PRIVATE_MASTERS_REFS == ()
    finally:
        importlib.reload(config)
