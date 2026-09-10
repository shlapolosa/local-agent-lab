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
VERSION = "v0.27"

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
}


#: How a CONSUMER reads each artifact — `whole` for the small complete registers a step reads in
#: full (a limit that truncated the facet schema would drop a rule), `key` for everything else.
#: Declared here because this script is the corpus's publication of record; the publisher freezes
#: it on the version.
RETRIEVAL = {
    "determinism-criteria": "whole", "facet-schema": "whole", "facet-schema-defaults": "whole",
    "facet-schema-readers": "whole", "surface-enforceability": "whole",
    "reference-architecture-components": "whole", "intake-fields": "whole",
    "capability-domains": "whole", "criticality-taxonomy": "whole", "readiness-gates": "whole",
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


def master_for(artifact_id: str) -> Path:
    return MASTERS / f"{artifact_id.replace('-', '_')}.md"


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

    missing = sorted(a for a in ARTIFACTS if not master_for(a).exists())
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
    published = released = skipped = 0
    refs = {r.rsplit("/", 1)[-1]: r for r in config.REFERENCE_MODELS_REFS}
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
                print(f"FAILED {artifact_id}: {out.strip().splitlines()[-1]}")
                return 1
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
