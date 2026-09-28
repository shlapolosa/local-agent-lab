"""Publish the packaged CAFÉ seed into the governed corpus — an OPERATOR script, run once per
release of the framework.

One-off and TDD-exempt (CLAUDE.md's scripts exemption), but it carries one decision worth stating:
the artifact IDS and RECORD TYPES here are a CONTRACT, not a convention. `decision-mcp`'s `RULES`
map looks artifacts up by these exact ids, and a lookup asks for records by their record type — so
a rename here silently returns nothing, which reads downstream as "the corpus has no guardrails"
rather than as a typo. The parity check at the bottom fails loudly instead.

    set -a && source .env && set +a
    source var/run/reference_signing_key          # the private seed, operator-only
    .venv/bin/python scripts/publish_usecase_corpus.py [--release]
"""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab.core.semantic.reference.baguild import KNOWN            # noqa: E402  stem -> (scheme, title)
from lab.platform import config                                    # noqa: E402
from lab.platform.contracts import VectorStores                    # noqa: E402
MASTERS = ROOT / "src" / "lab" / "core" / "usecase" / "seed" / "masters"
#: The corpus version this script publishes. BUMP IT whenever a master's bytes change — the
#: masters are the signed input, and re-publishing changed content under an unchanged version is
#: refused by the store. It is also why this is one constant rather than a per-artifact version: a
#: corpus whose artifacts drift apart in version cannot be pinned coherently, and the one time an
#: artifact was corrected on its own (v0.25.1) the next corpus-wide run silently RE-RELEASED the
#: older v0.25 over it, because that is the version this script releases.
VERSION = "v0.30"

#: artifact_id -> (record_type, natural key, owner). The id is the corpus's name for the artifact
#: and differs from the file stem where a consumer already spells it differently.
#: artifact_id -> (record_type, natural key, owner).
#:
#: The KEY is the master's own first column in almost every case, and that is the point: the
#: natural key is what a person looking at the published table would use to name a row, so a
#: lookup by it is a lookup somebody can check by eye. Where a table's first column repeats
#: (`ai-capability-map` names a domain many times) the key is the pair that is actually unique.
#: These were read off the masters rather than guessed — the first attempt assumed `id` throughout
#: and failed on the seventh artifact, which is the right place for it to fail.
ARTIFACTS = {
    "guardrails": ("guardrail", "id", "architecture governance"),
    "retired-guardrails": ("retired-guardrail", "Retired", "architecture governance"),
    "guardrail-mapping": ("risk-class", "Class", "architecture governance"),
    "family-triggers": ("family", "id", "architecture governance"),
    "component-families": ("family", "Family", "architecture governance"),
    "criticality-taxonomy": ("criticality-class", "Class", "architecture governance"),
    "determinism-criteria": ("criterion", "#", "architecture governance"),
    "facet-schema": ("facet", "Facet", "architecture governance"),
    "readiness-gates": ("gate", "Gate", "architecture governance"),
    "risk-derivation": ("risk-rule", "Exposure,Influence", "architecture governance"),
    # The reference architecture, as RECORDS. It was published as prose because the renderer only
    # understood one shape (a list of dicts) and this is a nested model — and prose needs an index,
    # which needs an embedder this lab does not have, so it published as nothing at all. It is
    # structure, and it now renders as structure: one artifact per section, diagram geometry
    # dropped because where a zone is drawn is not part of the architecture.
    "reference-architecture": ("archetype", "id", "architecture governance"),
    "reference-architecture-zones": ("zone", "id", "architecture governance"),
    # Keyed by the ID a design selects and a price line names (scripts/seed_components.py), so
    # the cited identity and the exact lookup agree; zone and name stay as columns.
    "reference-architecture-components": ("component", "id", "architecture governance"),
    # Deterministic cost: the price catalogue keyed by the component each line prices and the
    # variant it is bought as (opex three-point, envelope, volume band); see
    # scripts/seed_components.py for how it is derived from the price sheet.
    "component-prices": ("component-price", "component,variant", "finance"),
    "reference-architecture-detail": ("archetype-detail", "id", "architecture governance"),
    "reference-architecture-topologies": ("topology", "id", "architecture governance"),
    "reference-architecture-topology-archetypes": ("topology-archetype", "id",
                                                   "architecture governance"),
    "reference-architecture-guardrail-origin": ("guardrail-origin", "id",
                                                "architecture governance"),
    "surface-enforceability": ("obligation", "Obligation", "architecture governance"),
    "ai-capability-map": ("capability", "domain,capability", "architecture governance"),
    "capability-domains": ("domain", "domain", "architecture governance"),
    # The review app's roadmap: the published methodology joined to the implementation's step
    # numbers, record keys and AGENTS. Derived by scripts/derive_process_step_keys.py, because
    # `substrate` may not import `workloads` to read `Step.service` directly.
    "process-step-keys": ("step-key", "Step,Number", "architecture governance"),
    # The intake GROUPS, split into typed fields so the Submit form is generated from the artifact.
    # Finance owns them for the same reason it owns the groups they came from.
    "intake-field-specs": ("intake-field", "Field", "finance"),
    "capability-map-rules": ("capability-rule", "A capability is", "architecture governance"),
    "composition-moves": ("move", "Move", "architecture governance"),
    "tradeoff-catalogue": ("tradeoff", "Conflict", "architecture governance"),
    "archetypes": ("archetype", "code", "architecture governance"),
    "quality-attributes": ("quality-attribute", "Part", "architecture governance"),
    "building-block-schema": ("building-block-field", "Field", "architecture governance"),
    "service-contract-schema": ("service-contract-field", "Field", "architecture governance"),
    "decision-record-schema": ("decision-record-field", "Field", "architecture governance"),
    "domain-model": ("term", "Concept", "architecture governance"),
    "process-steps": ("process-step", "Step", "architecture governance"),
    "input-artifacts": ("input-artifact", "Artifact", "architecture governance"),
    "output-artifacts": ("output-artifact", "Artifact", "architecture governance"),
    "opportunity-obligations": ("opportunity-obligation", "ID", "architecture governance"),
    "source-register": ("source", "id", "architecture governance"),
    "build-surface": ("build-surface-question", "Q", "architecture governance"),
    # Finance's half of the corpus — a different owner and a different release cadence, which is
    # the whole reason valuation-mcp is a separate server from decision-mcp.
    "intake-fields": ("field-group", "Field group", "finance"),
    "business-case-sections": ("section", "#", "finance"),
    "benefit-drivers": ("driver", "Driver", "finance"),
    "cost-formulas": ("cost-formula", "Quantity", "finance"),
    "financial-formulas": ("financial-formula", "Quantity", "finance"),
    "price-sheet": ("price-line", "Service", "finance"),
    # SECTIONS of a multi-table artifact, published separately because the corpus is one record
    # type per artifact — see `masters_for` in the extractor. Concatenating them produced a record
    # set whose natural key collided, which the publisher refused rather than resolving silently.
    "facet-schema-defaults": ("facet-default", "Activity", "architecture governance"),
    "facet-schema-readers": ("facet-reader", "Facet", "architecture governance"),
    "capability-map-rules-heatmap": ("heatmap-dimension", "Dimension",
                                     "architecture governance"),
    "capability-map-rules-levels": ("capability-level", "Level", "architecture governance"),
    "component-families-modifiers": ("family-modifier", "Modifier", "architecture governance"),
    "quality-attributes-envelope-patterns": ("envelope-pattern", "Pattern",
                                             "architecture governance"),
    "readiness-gates-verdicts": ("readiness-verdict", "Verdict", "architecture governance"),
    "risk-derivation-classes": ("risk-class-scale", "Class", "architecture governance"),
    "risk-derivation-moves": ("risk-move", "Move", "architecture governance"),
    # --- The CAFÉ bundle of 28 Sep 2026 (cafe-artifacts.xlsx), imported by
    # scripts/artifacts_workbook.py. Keys were VERIFIED unique and non-empty against the rows, not
    # guessed; record types name one row; owners are the workbook's own. Several are PRIVATE — see
    # `PRIVATE` below.
    "ai-as-is-architecture": ("ai-as-is-architecture", "service name", "Platform and AI operations"),
    "business-capability-l1": ("business-capability-l1", "id", "Enterprise architecture"),
    "business-capability-l2": ("business-capability-l2", "id", "Enterprise architecture"),
    "business-capability-l3": ("business-capability-l3", "id", "Enterprise architecture"),
    "business-capability-levelling-flags": ("business-capability-levelling-flag", "id", "Enterprise architecture"),
    "criticality-crmf-alignment": ("criticality-crmf-alignment", "class", "Architecture Board"),
    "criticality-crmf-rules": ("criticality-crmf-rule", "#", "Architecture Board"),
    "criticality-tier-alignment": ("criticality-tier-alignment", "class", "Architecture Board"),
    "delivery-rate-assumptions": ("delivery-rate-assumption", "assumption", "Finance"),
    "foundry-coverage": ("foundry-coverage", "foundry_capability", "Architecture Board"),
    "logical-building-blocks": ("logical-building-block", "id", "Agent Council"),
    "ontology-competency-questions": ("ontology-competency-question", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-concepts": ("ontology-concept", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-exchange-standards": ("ontology-exchange-standard", "platform,standard", "Domain stewards; Ontology Council arbitrates"),
    "ontology-gaps": ("ontology-gap", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-identifiers": ("ontology-identifier", "identifier", "Domain stewards; Ontology Council arbitrates"),
    "ontology-indicator-links": ("ontology-indicator-link", "from,concept", "Domain stewards; Ontology Council arbitrates"),
    "ontology-indicators": ("ontology-indicator", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-modules": ("ontology-module", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-relationships": ("ontology-relationship", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-rules": ("ontology-rule", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-sources": ("ontology-source", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-states": ("ontology-state", "id", "Domain stewards; Ontology Council arbitrates"),
    "ontology-terminology-bindings": ("ontology-terminology-binding", "concept", "Domain stewards; Ontology Council arbitrates"),
    "platform-architecture-principles": ("platform-architecture-principle", "domain,principle", "Agent Council"),
    "quality-attributes-continuity-tiers": ("quality-attributes-continuity-tier", "tier", "Architecture Board"),
    "reference-architecture-coverage": ("reference-architecture-coverage", "l3", "Agent Council"),
    "reference-architecture-flows": ("reference-architecture-flow", "id", "Agent Council"),
    "reference-architecture-patterns": ("reference-architecture-pattern", "id", "Agent Council"),
    "reference-architecture-principles": ("reference-architecture-principle", "id", "Agent Council"),
    "reference-architecture-retired-components": ("reference-architecture-retired-component", "id", "Agent Council"),
    "retired-capability-ids": ("retired-capability-id", "retired", "Enterprise architecture"),
    "retired-realisation-rows": ("retired-realisation-row", "capability", "Architecture Board"),
    "risk-acceptance-authority": ("risk-acceptance-authority", "decision", "Information Security Office (risk function); ISGC oversees"),
    "risk-class-to-crmf": ("risk-class-to-crmf", "cafe_class", "Agent Council"),
    "risk-class-to-crmf-rules": ("risk-class-to-crmf-rule", "#", "Agent Council"),
    "risk-process": ("risk-process", "stage", "Information Security Office (risk function); ISGC oversees"),
    "risk-raci": ("risk-raci", "activity", "Information Security Office (risk function); ISGC oversees"),
    "risk-rating-bands": ("risk-rating-band", "rating", "Information Security Office (risk function); ISGC oversees"),
    "risk-register-schema": ("risk-register-schema", "field", "Information Security Office (risk function); ISGC oversees"),
    "risk-response": ("risk-response", "residual_level", "Information Security Office (risk function); ISGC oversees"),
    "risk-response-options": ("risk-response-option", "option", "Information Security Office (risk function); ISGC oversees"),
    "risk-scales-cia": ("risk-scales-cia", "level", "Information Security Office (risk function); ISGC oversees"),
    "risk-scales-likelihood": ("risk-scales-likelihood", "rating", "Information Security Office (risk function); ISGC oversees"),
    "risk-scales-vulnerability": ("risk-scales-vulnerability", "rating", "Information Security Office (risk function); ISGC oversees"),
    "technology-capability-l1": ("technology-capability-l1", "id", "Enterprise architecture"),
    "technology-capability-l2": ("technology-capability-l2", "id", "Enterprise architecture"),
    "technology-capability-l3": ("technology-capability-l3", "id", "Enterprise architecture"),
    "traditional-as-is-architecture": ("traditional-as-is-architecture", "service name", "Application owners"),
    "traditional-capabilities": ("traditional-capability", "id", "Enterprise architecture"),
    "traditional-capability-domains": ("traditional-capability-domain", "id", "Enterprise architecture"),
    "traditional-capability-realisation": ("traditional-capability-realisation", "capability,platform", "Enterprise architecture"),
    "traditional-rating-scale": ("traditional-rating-scale", "score", "Enterprise architecture"),
    "workload-placement-archetypes": ("workload-placement-archetype", "id", "Agent Council"),
    "workload-placement-intake": ("workload-placement-intake", "gate", "Agent Council"),
    "workload-placement-principles": ("workload-placement-principle", "id", "Agent Council"),
    "workload-placement-seven-rs": ("workload-placement-seven-r", "disposition", "Agent Council"),
    "workload-placement-stages": ("workload-placement-stage", "stage", "Agent Council"),
}


#: How a CONSUMER reads each artifact — `whole` for the small complete registers a step reads in
#: full (a limit that truncated the facet schema would drop a rule), `key` for everything else.
#: Declared here because this script is the corpus's publication of record; the publisher freezes
#: it on the version.
RETRIEVAL = {
    "determinism-criteria": "whole", "facet-schema": "whole", "facet-schema-defaults": "whole",
    "facet-schema-readers": "whole", "surface-enforceability": "whole",
    "reference-architecture-components": "whole", "intake-fields": "whole",
    # Both are small complete registers a form or a roadmap reads ENTIRELY — "the relevant rows" of
    # a process is not a process.
    "process-step-keys": "whole", "intake-field-specs": "whole",
    # Step 5 matches every function against the WHOLE technology map (74 rows). "The relevant rows"
    # would decide relevance before the step whose job that is — CAFÉ's own rule for a small
    # complete register is to read every record.
    "ai-capability-map": "whole",
    "capability-domains": "whole", "criticality-taxonomy": "whole", "readiness-gates": "whole",
    # The CAFÉ bundle's own `Read as: whole` declarations. Every other table it carries says `key`,
    # the record default — and none of its modes disagreed with a mode already declared here.
    "ai-as-is-architecture": "whole",
    "business-capability-l3": "whole",
    "logical-building-blocks": "whole",
    "ontology-concepts": "whole",
    "ontology-indicator-links": "whole",
    "ontology-relationships": "whole",
    "reference-architecture-coverage": "whole",
    "risk-register-schema": "whole",
    "technology-capability-l3": "whole",
    "traditional-as-is-architecture": "whole",
    "traditional-capabilities": "whole",
}

#: The licensed capability WORKBOOKS — never a file in this repository. The artifact id IS the
#: gateway's store id (`contracts.VectorStores`, the one declaration) and the scheme name and title
#: are the semantic layer's own (`baguild.KNOWN`), so a corpus row, a scheme concept and a store
#: agree on identity. The `art://` ref comes from REFERENCE_MODELS_REFS — the same refs
#: semantic-mcp materialises — so this table carries no store path.
WORKBOOKS = {
    VectorStores.CAPABILITY_MAP_HEALTHCARE: "healthcare-provider-v2.0",
    VectorStores.CAPABILITY_MAP_INSURANCE: "insurance-v5.0",
}
assert set(WORKBOOKS) == VectorStores.names(), "a store the corpus does not publish, or the reverse"
assert set(WORKBOOKS.values()) <= set(KNOWN), "a workbook stem the semantic layer does not know"


#: Artifacts whose masters may NOT be committed: this repository is PUBLIC, and these tables come
#: from tenant documents that are RESTRICTED or whose classification is not stated. User decision,
#: 28 Sep 2026 — they reach the corpus BY REFERENCE (`REFERENCE_PRIVATE_MASTERS_REFS`, the private
#: artifact store), the path the licensed BA Guild workbooks already take, until each source is
#: cleared. The value is WHY: an unexplained entry is one somebody deletes to make a publish go
#: through. `tests/governance/test_restricted_corpus_stays_private.py` also reads the CONTENT of
#: every committed master, so an import that forgets this list still fails.
PRIVATE: dict[str, str] = {
    "build-surface":
        "its S1.4 row applies the ADHDS workload placement strategy, from the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "criticality-crmf-alignment":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "criticality-crmf-rules":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "criticality-tier-alignment":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "delivery-rate-assumptions":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "ontology-competency-questions":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-concepts":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-exchange-standards":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-gaps":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-identifiers":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-indicator-links":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-indicators":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-modules":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-relationships":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-rules":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-sources":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-states":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "ontology-terminology-bindings":
        "the ontology, whose modules, concepts and sources cite ADHDS documents (the Target State Architecture, the AI use-case catalogue) — one graph, so private whole; classification not stated",
    "platform-architecture-principles":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "quality-attributes-continuity-tiers":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "risk-acceptance-authority":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-class-to-crmf":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-class-to-crmf-rules":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-process":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-raci":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-rating-bands":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-register-schema":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-response":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-response-options":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-scales-cia":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-scales-likelihood":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "risk-scales-vulnerability":
        "the ADHDS Cyber Risk Management Framework v2.0 — Information Security Office, RESTRICTED",
    "traditional-as-is-architecture":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "traditional-capabilities":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "traditional-capability-domains":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "traditional-capability-realisation":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "traditional-rating-scale":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "workload-placement-archetypes":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "workload-placement-intake":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "workload-placement-principles":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "workload-placement-seven-rs":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
    "workload-placement-stages":
        "the ADHDS Target State Architecture v1 (an Accenture deliverable) — classification not stated",
}

#: Where a private master is written by the importer, and read from before it is uploaded: inside
#: the git-ignored var/ tree, never under src/.
PRIVATE_DIR = Path(config.REFERENCE_MODELS_DIR) / "cafe-private"


def private_refs(refs) -> dict[str, str]:
    """`REFERENCE_PRIVATE_MASTERS_REFS` keyed by file name — refusing two refs that share one, which
    would otherwise resolve last-wins to whichever the setting happened to list second."""
    out: dict[str, str] = {}
    for ref in (r.strip() for r in refs if r.strip()):
        name = ref.rsplit("/", 1)[-1]
        if name in out:
            raise ValueError(f"two private refs share the same file name {name!r}: "
                             f"{out[name]} and {ref}")
        out[name] = ref
    return out


def private_source(artifact_id: str, refs: dict[str, str], fetch) -> tuple[list[str] | None, str]:
    """The publish arguments for one PRIVATE master, or `None` and the reason it is deferred.

    The master is published from its `art://` ref — and the ref must hold EXACTLY the file this
    repository's importer last wrote, when that file is here to compare. Re-import, forget to
    re-upload, publish: the ref still holds last release's rows, and they would go out signed under
    the new version, silently, for content that may not be public (review F4, 28 Sep 2026).
    `fetch(ref) -> bytes` is the artifact store's read — the same one the publisher makes."""
    name = master_for(artifact_id).name
    if name not in refs:
        return None, (f"private ({PRIVATE[artifact_id].split(' — ')[0]}), and "
                      f"REFERENCE_PRIVATE_MASTERS_REFS carries no {name}")
    local = master_for(artifact_id)
    if local.is_file() and hashlib.sha256(local.read_bytes()).digest() != hashlib.sha256(
            fetch(refs[name])).digest():
        return None, (f"the uploaded {refs[name]} is not the file imported at {local} — upload the "
                      f"imported master again before publishing")
    return ["--master-ref", refs[name], "--master-format", "markdown"], ""


def master_for(artifact_id: str) -> Path:
    stem = f"{artifact_id.replace('-', '_')}.md"
    return (PRIVATE_DIR if artifact_id in PRIVATE else MASTERS) / stem


def already_published() -> set[str]:
    """What this version already holds. Publishing is idempotent from the OPERATOR's side — a
    re-run after fixing one artifact must not need the other thirty-four undone first."""
    code, out = run("list")
    if code:
        return set()
    # The STATUS column too: a `draft` or withdrawn version at this version string would otherwise
    # count as published and be skipped forever — precisely the "re-run after fixing one artifact"
    # case this exists for.
    return {parts[0] for parts in (line.split() for line in out.splitlines())
            if len(parts) > 2 and parts[1] == VERSION and parts[2] == "published"}


def _store():
    """The artifact store the publisher reads a `--master-ref` from — built lazily, because only a
    run that publishes a private master needs it."""
    from lab.substrate import container
    return container.build("reference-publish").artifacts()


def run(*args: str) -> tuple[int, str]:
    out = subprocess.run([sys.executable, "-m", "lab.substrate.reference.publish", *args],
                         capture_output=True, text=True, cwd=ROOT)
    return out.returncode, (out.stdout or "") + (out.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", action="store_true",
                    help="also release each version to the general ring")
    ap.add_argument("--ring", type=int, default=0,
                    help="0 (pilot) is where a first release belongs — CR-18's soak means a "
                         "version cannot skip a ring, and skipping is not a faster rollout")
    ap.add_argument("--actor", default="operator")
    args = ap.parse_args()

    # A PRIVATE master is not in this repository by design — it is published from its `art://`
    # ref, and a missing ref is a deferral named in the loop below, not a missing master.
    missing = sorted(a for a in ARTIFACTS if a not in PRIVATE and not master_for(a).exists())
    extra = sorted(p.stem.replace("_", "-") for p in MASTERS.glob("*.md")
                   if p.stem.replace("_", "-") not in ARTIFACTS)
    stray = sorted(set(RETRIEVAL) - set(ARTIFACTS))
    if missing or extra or stray:
        # Loud, because the failure mode is silent: an unpublished artifact makes every lookup
        # against it return nothing, which downstream reads as "the corpus says there are none" —
        # and a misspelt RETRIEVAL key publishes a register as `key`, truncating it at the limit.
        print(f"masters missing for {missing}; masters with no entry here: {extra}; "
              f"RETRIEVAL names no artifact: {stray}")
        return 1

    have = already_published()
    deferred: dict[str, str] = {}                         # artifact -> why it is not in this run
    failures: dict[str, str] = {}                         # artifact -> why it could not be published
    published = released = skipped = 0
    refs = {r.rsplit("/", 1)[-1]: r for r in config.REFERENCE_MODELS_REFS}
    by_name = private_refs(config.REFERENCE_PRIVATE_MASTERS_REFS)
    everything = {**{a: ("markdown",) + spec for a, spec in ARTIFACTS.items()},
                  **{a: ("workbook", "capability", "id,parent,level", "BA Guild") for a in WORKBOOKS}}
    for artifact_id, (fmt, record_type, key, owner) in sorted(everything.items()):
        if artifact_id in have:
            skipped += 1
        else:
            kind = "record" if record_type else "prose"
            if fmt == "workbook":
                stem = WORKBOOKS[artifact_id]
                scheme, title = KNOWN[stem]
                if f"{stem}.xlsx" not in refs:
                    deferred[artifact_id] = f"REFERENCE_MODELS_REFS carries no {stem}.xlsx"
                    print(f"  {artifact_id:38} deferred — {deferred[artifact_id]}")
                    continue
                source = ["--master-ref", refs[f"{stem}.xlsx"], "--master-format", "workbook",
                          "--scheme", scheme, "--title", title, "--retrieval", "vector",
                          "--text-fields", "path,definition"]
            elif artifact_id in PRIVATE:
                source, why = private_source(artifact_id, by_name, fetch=_store().get)
                if source is None:
                    deferred[artifact_id] = why
                    print(f"  {artifact_id:38} deferred — {why}")
                    continue
                if artifact_id in RETRIEVAL:
                    source += ["--retrieval", RETRIEVAL[artifact_id]]
            else:
                source = ["--master", str(master_for(artifact_id))]
                if artifact_id in RETRIEVAL:
                    source += ["--retrieval", RETRIEVAL[artifact_id]]
            code, out = run("publish", artifact_id, *source,
                            "--version", VERSION, "--kind", kind,
                            "--record-type", record_type, "--key-fields", key, "--owner", owner)
            if code and "no embedder is configured" in out:
                # Not a failure of this run. A prose artifact published without an index would be a
                # version `reference_search` must refuse, and the publisher is right to refuse it
                # first. It becomes publishable the day REFERENCE_EMBED_MODEL is set, and until
                # then it is DEFERRED and named — an artifact silently absent from the corpus is
                # read downstream as "the corpus says there is none".
                deferred[artifact_id] = "retrieved semantically, and no embedder is configured"
                print(f"  {artifact_id:38} deferred — {deferred[artifact_id]}")
                continue
            if code:
                # NAMED AND CARRIED ON, not `return 1`. Stopping here stranded every artifact
                # alphabetically after the failure: measured 19 Sep 2026, one unreadable workbook
                # took down a publish at artifact 8 of 55 and the 47 behind it — none of which had
                # anything wrong — simply never ran. The reason is the same one this script already
                # gives for a deferral: an artifact silently absent from the corpus is read
                # downstream as "the corpus says there is none", and 47 of those is worse than one.
                # The exit code still reports the failure, so nothing passes unnoticed.
                failures[artifact_id] = out.strip().splitlines()[-1]
                print(f"  {artifact_id:38} FAILED — {failures[artifact_id]}")
                continue
            published += 1
        if args.release:
            code, out = run("release", artifact_id, VERSION, "--ring", str(args.ring),
                            "--actor", args.actor)
            if code:
                print(f"published but NOT released {artifact_id}: "
                      f"{out.strip().splitlines()[-1]}")
            else:
                released += 1
        print(f"  {artifact_id:38} {record_type or 'prose'}")
    print(f"\n{published} published, {skipped} already at {VERSION}, "
          f"{released} released to ring {args.ring}")
    for artifact_id, why in deferred.items():
        print(f"deferred {artifact_id}: {why}")
    for artifact_id, why in failures.items():
        print(f"FAILED {artifact_id}: {why}", file=sys.stderr)
    # Non-zero when anything failed — every OTHER artifact is published, and the operator is told
    # exactly which ones were not. A green run that published 8 of 55 is the outcome to avoid.
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
