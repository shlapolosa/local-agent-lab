"""Guardrail trigger predicates — parsed from the published artifact, evaluated against a step.

NFR-15: "gate definitions, derivation rules, guardrail predicates and the reference architecture
model are read as configuration by a service, never compiled into the orchestrator." So the 24 live
guardrails are not 24 Python functions. They arrive as the small expression language the CAFÉ
artifact publishes:

    G08  step.determinism ≥ D2 ∨ step invokes a downstream service
    G09  step.effect ∈ {external communication, ...} ∧ step.authorisation ≠ per-action human
    G19  ∃ step in workflow with influence ≥ 3
    G01  always — every step executed by an agent

Two term kinds, because the corpus has two. A COMPARISON reads a facet off the step's vector. A
NAMED CONDITION is prose the vector cannot answer ("step invokes any registered tool") and the
CALLER must supply — step 19 knows what a step invokes; a facet schema does not.

The one rule everything here is built around: **an unanswered condition refuses, it never reads
False**. A guardrail that quietly fails to fire is the failure this whole layer exists to prevent,
and it is invisible — the run completes, the control set is short, and nothing says so. Short-
circuiting is still honest where the unknown cannot change the answer (`False ∧ unknown` is False),
and only there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = [
    "FIELDS", "Predicate", "PredicateError", "PredicateSyntaxError", "UnknownCondition",
    "UnknownField", "parse", "normalise_value",
]

AND, OR = "∧", "∨"
EXISTS = "∃ step in workflow with"
OPERATORS = ("∈", "≠", "≥", "≤", "=", ">", "<")

#: Facets a predicate may read, spelled as the published facet schema spells them. `step.` is a
#: prefix the corpus uses inconsistently (`step.determinism` but bare `influence`), so it is
#: stripped before lookup rather than modelled.
FIELDS = frozenset({
    "activity", "determinism", "effect", "reversibility", "blast_radius", "audience",
    "authorisation", "domain", "input.sensitivity", "input.trust", "input.freshness",
    "exposure", "influence", "criticality",
})

#: Where the facet schema and the predicates spell one value differently. The schema says
#: "a cohort · the whole population"; the predicates say "{cohort, population}". Same value.
SYNONYMS = {
    "whole population": "population",
    "restricted/regulated": "restricted",
    "time critical": "time-critical",
    "safety of life": "safety-of-life",
}

_ARTICLE = re.compile(r"^(?:a|an|the)\s+")
_DET_TIER = re.compile(r"^d([0-3])$")


class PredicateError(ValueError):
    """A predicate could not be read, or could not be answered."""


class PredicateSyntaxError(PredicateError):
    """The published text is not a predicate this grammar can read."""


class UnknownField(PredicateError):
    """The predicate reads a facet that is not in the schema."""


class UnknownCondition(PredicateError):
    """A named condition the caller did not answer, and whose answer would decide the predicate."""


def normalise_value(value: Any) -> Any:
    """One spelling per value, so the schema's wording and the predicate's wording compare equal."""
    if not isinstance(value, str):
        return value
    text = _ARTICLE.sub("", value.strip().lower())
    return SYNONYMS.get(text, text)


def _normalise_field(name: str) -> str:
    name = name.strip().lower().removeprefix("step.")
    return name.replace(" ", "_")


def _ordinal(value: Any) -> float:
    """A rank for ≥ and friends. Tiers are D0..D3; classes are already numbers."""
    if isinstance(value, bool):
        raise PredicateError(f"cannot order a boolean: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    tier = _DET_TIER.match(text)
    if tier:
        return float(tier.group(1))
    try:
        return float(text)
    except ValueError:
        raise PredicateError(
            f"{value!r} has no order — only numbers and determinism tiers D0-D3 can be compared"
        ) from None


# ---------------------------------------------------------------- the tree

class Predicate:
    """A parsed trigger predicate. Immutable and reusable across steps."""

    def evaluate(self, facts: Mapping[str, Any], *,
                 workflow: Sequence[Mapping[str, Any]] = (),
                 conditions: Mapping[str, bool] | None = None) -> bool:
        raise NotImplementedError                                   # pragma: no cover

    def conditions(self) -> frozenset[str]:
        """The named conditions this predicate needs answered, so a caller can supply them all."""
        return frozenset()

    def qualifiers(self) -> tuple[str, ...]:
        """Prose the artifact attaches to a term but that is not itself evaluated.

        One guardrail carries one: G24's "on either the instance or systematic reading" tells a
        reader HOW to read blast radius, and it widens the trigger rather than narrowing it. It is
        surfaced rather than silently dropped so step 19 can put it on the obligation."""
        return ()


@dataclass(frozen=True)
class Always(Predicate):
    note: str = ""

    def evaluate(self, facts, *, workflow=(), conditions=None) -> bool:
        return True

    def qualifiers(self):
        return (self.note,) if self.note else ()


@dataclass(frozen=True)
class Comparison(Predicate):
    field_name: str
    op: str
    values: tuple[Any, ...]
    note: str = ""

    def evaluate(self, facts, *, workflow=(), conditions=None) -> bool:
        name = self.field_name
        if name not in FIELDS:
            raise UnknownField(
                f"{name!r} is not a facet in the schema; known facets are {sorted(FIELDS)}")
        if name not in facts:
            raise UnknownField(f"the step does not carry the facet {name!r}")
        actual = normalise_value(facts[name])
        if self.op == "∈":
            return actual in self.values
        if self.op == "=":
            return actual == self.values[0]
        if self.op == "≠":
            return actual != self.values[0]
        left, right = _ordinal(actual), _ordinal(self.values[0])
        return {"≥": left >= right, "≤": left <= right,
                ">": left > right, "<": left < right}[self.op]

    def qualifiers(self):
        return (self.note,) if self.note else ()


@dataclass(frozen=True)
class Named(Predicate):
    """Prose the facet vector cannot answer. The caller knows; the schema does not."""
    text: str

    def evaluate(self, facts, *, workflow=(), conditions=None) -> bool:
        answers = conditions or {}
        if self.text not in answers:
            raise UnknownCondition(
                f"nothing answered the condition {self.text!r}. Supply it in `conditions=` — it "
                f"is not assumed false, because a guardrail that silently fails to fire is the "
                f"defect this refusal exists to prevent.")
        return bool(answers[self.text])

    def conditions(self) -> frozenset[str]:
        return frozenset({self.text})


@dataclass(frozen=True)
class Exists(Predicate):
    """`∃ step in workflow with <expr>` — a property of the workflow, not of the step in hand."""
    inner: Predicate

    def evaluate(self, facts, *, workflow=(), conditions=None) -> bool:
        return any(self.inner.evaluate(s, workflow=workflow, conditions=conditions)
                   for s in workflow)

    def conditions(self) -> frozenset[str]:
        return self.inner.conditions()

    def qualifiers(self):
        return self.inner.qualifiers()


@dataclass(frozen=True)
class Junction(Predicate):
    """`∧` or `∨` over two or more terms, with honest short-circuiting.

    An unanswered condition is only fatal when it could change the answer: `False ∧ unknown` is
    False whatever the unknown turns out to be, and `True ∨ unknown` is True. Anything else
    refuses."""
    op: str
    terms: tuple[Predicate, ...] = field(default_factory=tuple)

    def evaluate(self, facts, *, workflow=(), conditions=None) -> bool:
        decisive = self.op == OR                       # True decides an ∨; False decides an ∧
        pending: PredicateError | None = None
        for term in self.terms:
            try:
                if term.evaluate(facts, workflow=workflow, conditions=conditions) is decisive:
                    return decisive
            except UnknownCondition as exc:
                pending = pending or exc
        if pending is not None:
            raise pending
        return not decisive

    def conditions(self) -> frozenset[str]:
        return frozenset().union(*(t.conditions() for t in self.terms))

    def qualifiers(self):
        return tuple(q for t in self.terms for q in t.qualifiers())


# ---------------------------------------------------------------- the parser

def _split_top(text: str, sep: str) -> list[str]:
    return [part.strip() for part in text.split(sep)] if sep in text else [text.strip()]


def _parse_values(text: str) -> tuple[tuple[Any, ...], str]:
    """A `{a, b, c}` set or a single bare value, plus any prose trailing a closing brace."""
    text = text.strip()
    if text.startswith("{"):
        end = text.find("}")
        if end < 0:
            raise PredicateSyntaxError(f"unclosed value set in {text!r}")
        items = tuple(normalise_value(v) for v in text[1:end].split(",") if v.strip())
        if not items:
            raise PredicateSyntaxError(f"empty value set in {text!r}")
        return items, text[end + 1:].strip()
    if not text:
        raise PredicateSyntaxError("a comparison needs a value on the right")
    return (normalise_value(text),), ""


def _parse_term(text: str) -> Predicate:
    text = text.strip()
    if not text:
        raise PredicateSyntaxError("empty term — a stray ∧ or ∨")
    if text.startswith(EXISTS):
        return Exists(_parse_or(text[len(EXISTS):]))
    for op in OPERATORS:
        head, sep, tail = text.partition(op)
        if sep and head.strip():
            values, note = _parse_values(tail)
            return Comparison(_normalise_field(head), op, values, note)
    return Named(text)


def _parse_and(text: str) -> Predicate:
    terms = [_parse_term(t) for t in _split_top(text, AND)]
    return terms[0] if len(terms) == 1 else Junction(AND, tuple(terms))


def _parse_or(text: str) -> Predicate:
    terms = [_parse_and(t) for t in _split_top(text, OR)]
    return terms[0] if len(terms) == 1 else Junction(OR, tuple(terms))


def parse(text: str) -> Predicate:
    """Read a published trigger predicate. Raises `PredicateSyntaxError` on anything else."""
    if not isinstance(text, str) or not text.strip():
        raise PredicateSyntaxError("a predicate cannot be empty")
    body = text.strip()
    if body.lower().startswith("always"):
        _, _, note = body.partition("—")
        return Always(note.strip())
    return _parse_or(body)
