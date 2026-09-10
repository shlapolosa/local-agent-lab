"""Step 23 — the cost model: a JOIN of the selected components onto the price catalogue.

Cost is what the components a design SELECTED (step 21, by catalogue id — G04) cost at the
quality-attribute envelope the case demands, at the volume intake captured, priced against the
REFERENCE catalogue rather than a live pricing query. That is deliberate and it is what makes
estimates comparable: two submissions costed a week apart against a moving price feed are not
comparable, and a portfolio you cannot rank is not a portfolio. Every model therefore stamps the
catalogue VERSION it was costed against (CR-23, CR-24).

Nothing here is a judgement any more (user decision, 10 Sep 2026). The two judgements cost used
to hide — which line a component consumes, and where in its band it sits — moved upstream to
where they are already made and gated: the catalogue keys each line by `(component, variant)` and
says which envelopes may buy it, and intake captures the volume that positions a driven line.
Three refusals carry the weight:

* **FR-32** — a component with no line at this envelope is a GAP FLAG, never a proxy price;
* a driven line whose driver intake did not capture is `requires_input` and EXCLUDED, never
  positioned by guess — the total says what it leaves out;
* **FR-34** — a build cost states its provenance; an estimate is never presented as a quote.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "BuildCost", "CATALOGUE_CAVEAT", "CostError", "CostLine", "CostModel", "DRIVERS", "PriceLine",
    "Provenance", "ThreePoint", "build_cost", "catalogue", "cost_model", "envelope_for",
    "parse_estimate", "position", "volume_from_intake", "year_one_total",
]

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ENVELOPE = ("low", "expected", "high")

#: The volume assumptions intake captures, and the words a person uses for them. A driven price
#: line names one of these; an intake mapping is free text, so the number is found beside the word.
DRIVERS = {"runs_per_month": ("run", "transaction", "request", "conversation"),
           "users": ("user", "seat", "staff"),
           "records": ("record", "document", "row")}

#: What a catalogue-derived model says about itself. The figures are the reference catalogue's
#: (illustrative of the structure, Finance's to version in the corpus); the model is exact given
#: them. Carried on every model so a reader never mistakes one for a quote.
CATALOGUE_CAVEAT = ("Costed against the reference component-price catalogue at the pinned "
                    "version: its figures are illustrative of the structure and Finance's to "
                    "version. Every line cites the catalogue line it came from; nothing is "
                    "approximated — a component with no line is a gap flag, a driven line with "
                    "no captured volume is excluded and named.")

class CostError(ValueError):
    """A figure was asked for that the catalogue cannot honestly supply."""


class Provenance(StrEnum):
    QUOTE = "vendor quote"
    BUDGET = "budget bucket"
    ESTIMATE = "estimate"


@dataclass(frozen=True)
class ThreePoint:
    """A low / expected / high range. Carried through rather than collapsed (FR-31): the range is
    the only honest statement an estimate makes about its own uncertainty."""
    low: float
    expected: float
    high: float

    def __add__(self, other: "ThreePoint") -> "ThreePoint":
        return ThreePoint(self.low + other.low, self.expected + other.expected,
                          self.high + other.high)


def _number(value: Any, what: str) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise CostError(f"{what} is not a number: {value!r}") from exc


@dataclass(frozen=True)
class PriceLine:
    """One row of the component-price catalogue, typed — the ONE place a corpus cell becomes a
    number, so a `"175.0"` never reaches arithmetic as text and a malformed row refuses here."""
    component: str
    component_name: str
    variant: str
    unit: str
    opex: ThreePoint
    envelope_in: tuple[str, ...]
    volume_driver: str
    expected_at: float
    high_at: float
    capex: float | None = None
    source_line: str = ""
    note: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "PriceLine":
        component = str(row.get("component") or "").strip()
        variant = str(row.get("variant") or "").strip()
        if not component or not variant:
            raise CostError(f"a price line needs its component and variant: {dict(row)!r}")
        envelopes = row.get("envelope_in") or ()
        if isinstance(envelopes, str):
            envelopes = [e.strip() for e in envelopes.split(";") if e.strip()]
        envelopes = tuple(envelopes)
        if not envelopes or not set(envelopes) <= set(_ENVELOPE):
            raise CostError(f"{component}/{variant}: envelope_in must name low/expected/high; "
                            f"got {envelopes!r}")
        driver = str(row.get("volume_driver") or "none").strip()
        if driver != "none" and driver not in DRIVERS:
            raise CostError(f"{component}/{variant}: {driver!r} is not a volume driver intake "
                            f"captures ({sorted(DRIVERS)})")
        expected_at = _number(row.get("expected_at") or 0, "expected_at")
        high_at = _number(row.get("high_at") or 0, "high_at")
        if driver != "none" and not (0 < expected_at < high_at):
            raise CostError(f"{component}/{variant}: driven by {driver} but its bands are "
                            f"{expected_at}/{high_at} — a driven line with no bands would price "
                            f"every volume at the top of its range")
        capex_raw = row.get("capex_once")
        capex = None if capex_raw in ("", None) else _number(capex_raw, "capex_once")
        return cls(
            component=component, component_name=str(row.get("component_name") or component),
            variant=variant, unit=str(row.get("unit") or ""),
            opex=ThreePoint(_number(row.get("opex_low"), "opex_low"),
                            _number(row.get("opex_expected"), "opex_expected"),
                            _number(row.get("opex_high"), "opex_high")),
            envelope_in=envelopes, volume_driver=driver,
            expected_at=expected_at, high_at=high_at, capex=capex, source_line=str(row.get("source_line") or ""),
            note=str(row.get("note") or ""))


def catalogue(rows: Iterable[Mapping[str, Any]]) -> tuple[PriceLine, ...]:
    """The catalogue as typed lines. A malformed row refuses the whole catalogue: a cost model
    missing one line is a total that looks complete."""
    return tuple(PriceLine.from_row(r) for r in rows)


@dataclass(frozen=True)
class CostLine:
    """One PRICED line of a model: a catalogue line positioned at this case's volume."""
    component: str
    component_name: str
    variant: str
    unit: str
    monthly: ThreePoint
    volume_driver: str = "none"
    volume: float | None = None
    source_line: str = ""
    note: str = ""


@dataclass(frozen=True)
class BuildCost:
    amount: float
    provenance: Provenance
    basis: str


@dataclass(frozen=True)
class CostModel:
    lines: tuple[CostLine, ...]
    monthly: ThreePoint
    year_one: ThreePoint
    gap_flags: tuple[str, ...] = ()
    build: BuildCost | None = None
    requires_input: tuple[str, ...] = ()
    sheet_version: str = ""
    design_version: str = ""
    caveat: str = ""
    envelope: str = "expected"
    capex: float = 0.0


# ---------------------------------------------------------------- reading the sheet's figures

def parse_estimate(text: str) -> ThreePoint:
    """"~175" is a point, "~100–400" is a band, "Included" is nothing owed but still a line.

    Anything else refuses rather than reading as zero — a line nobody could price must not
    disappear into a total as free. (Used by the catalogue generator; the catalogue itself
    carries the three points.)"""
    body = (text or "").strip()
    if not body:
        raise CostError("a price line carries no estimate at all")
    if body.lower().startswith("included"):
        return ThreePoint(0.0, 0.0, 0.0)
    numbers = [float(n.replace(",", "")) for n in _NUMBER.findall(body)]
    if not numbers:
        raise CostError(f"{text!r} is not an estimate this sheet can price; it needs a figure or "
                        f"'Included'")
    low, high = numbers[0], numbers[-1]
    return ThreePoint(low, (low + high) / 2, high)


# ---------------------------------------------------------------- the two upstream decisions

def envelope_for(criticality: str) -> str:
    """Which envelope a case buys at — a RULE of the confirmed criticality class, not a pick.

    A safety-of-life case is provisioned for its worst day; a routine one is not. The class is a
    human's confirmed answer (step 12), so the envelope inherits its provenance."""
    table = {"routine": "low", "business-critical": "expected", "safety-of-life": "high"}
    key = str(criticality or "").strip().lower()
    if key not in table:
        raise CostError(f"{criticality!r} is not a criticality class an envelope follows from; "
                        f"expected one of {sorted(table)}")
    return table[key]


#: A period a person writes a volume in, and how many of it make a month. A number with no
#: period is taken as monthly — the driver's own unit — and said so in the docstring.
_PERIODS = (("day", 30.0), ("daily", 30.0), ("week", 4.33), ("weekly", 4.33),
            ("year", 1 / 12), ("annual", 1 / 12), ("month", 1.0), ("monthly", 1.0))
_QUANTITY = r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?(?![A-Za-z0-9])"


def _scale(raw: str, suffix: str | None) -> float:
    value = float(raw.replace(",", ""))
    return value * {"k": 1e3, "m": 1e6}.get((suffix or "").lower(), 1.0)


def _per_month(text_after: str) -> float:
    """The factor that turns a quantity into a monthly one, from the period written beside it."""
    for word, factor in _PERIODS:
        if re.search(rf"\b(?:per|a|an|each|every|/)\s*{word}", text_after, re.I) or \
                re.search(rf"\b{word}\b", text_after, re.I):
            return factor
    return 1.0


def volume_from_intake(intake: Mapping[str, Any] | None) -> dict[str, float]:
    """The volume assumptions a person captured at intake, as numbers per driver.

    An intake mapping is `label -> {field: text}` written by a human. Every group's text is
    scanned (a Finance rename of the group must not silently disable cost), and a driver is
    read from a quantity beside its word within one clause — "5k users", "12,000 runs a month",
    "records: 120000" — never across a `;`, `,` or `.`. `k`/`m` multiply; a period beside a
    RUN count is normalised to a month (per day ×30, per week ×4.33, per year ÷12); a count
    with no period is monthly, the driver's own unit. A driver not found is simply absent — the
    cost model then names the line it could not place rather than positioning it by guess."""
    text = " ".join(
        str(v) for fields in (intake or {}).values() if isinstance(fields, Mapping)
        for v in fields.values())
    found: dict[str, float] = {}
    for driver, words in DRIVERS.items():
        for word in words:
            before = re.search(_QUANTITY + rf"[^0-9;,.]{{0,25}}\b{word}[a-z]*\b", text, re.I)
            after = re.search(rf"\b{word}[a-z]*\b[^0-9;,.]{{0,25}}" + _QUANTITY, text, re.I)
            hit = before or after
            if not hit:
                continue
            raw, suffix = (hit.group(1), hit.group(2)) if hit is before else (hit.group(1), hit.group(2))
            value = _scale(raw, suffix)
            if driver == "runs_per_month":
                tail = text[hit.end():hit.end() + 30]
                value *= _per_month(tail)
            found[driver] = value
            break
    return found


def position(line: PriceLine, volume: Mapping[str, float]) -> ThreePoint | None:
    """Where in its band a line sits for THIS case, or None when intake did not capture the
    driver — the caller excludes and names it rather than guessing."""
    if line.volume_driver == "none":
        return line.opex
    value = volume.get(line.volume_driver)
    if value is None:
        return None
    if value < line.expected_at:
        placed = line.opex.low
    elif value < line.high_at:
        placed = line.opex.expected
    else:
        placed = line.opex.high
    return ThreePoint(line.opex.low, placed, line.opex.high)


# ---------------------------------------------------------------- the arithmetic

def year_one_total(monthly: ThreePoint, build: float) -> ThreePoint:
    """Sub-step 23.6 — build (and any one-off) plus twelve times the monthly run cost."""
    return ThreePoint(build + monthly.low * 12, build + monthly.expected * 12,
                      build + monthly.high * 12)


def build_cost(amount: float, provenance: Provenance) -> BuildCost:
    """Sub-step 23.5. The provenance is not decoration — FR-34 forbids presenting an estimate as a
    quote, and the only way to keep that true is to carry which one it is."""
    if not isinstance(provenance, Provenance):
        raise CostError("a build cost must state its provenance as a vendor quote, a budget "
                        f"bucket or an estimate; got {provenance!r}")
    return BuildCost(float(amount), provenance,
                     basis=f"build cost taken from the {provenance.value} captured at intake")


# ---------------------------------------------------------------- assembly

def cost_model(component_ids: Sequence[str], lines: Iterable[PriceLine], *, envelope: str,
               volume: Mapping[str, float] | None = None, build: BuildCost | None,
               design_version: str = "", sheet_version: str = "") -> CostModel:
    """The join. Every selected component, every catalogue variant valid at this envelope,
    each positioned at the captured volume — and every refusal named in the model."""
    if envelope not in _ENVELOPE:
        raise CostError(f"{envelope!r} is not an envelope; expected one of {list(_ENVELOPE)}")
    volume = dict(volume or {})
    by_component: dict[str, list[PriceLine]] = {}
    for line in lines:
        by_component.setdefault(line.component, []).append(line)

    priced: list[CostLine] = []
    gaps: list[str] = []
    requires: list[str] = []
    capex = 0.0
    uncapexed: list[str] = []
    for component in dict.fromkeys(str(c).strip() for c in component_ids if str(c).strip()):
        variants = [l for l in by_component.get(component, []) if envelope in l.envelope_in]
        if not variants:
            gaps.append(component)                       # FR-32 — a gap flag, never a proxy price
            continue
        for line in variants:
            placed = position(line, volume)
            if placed is None:
                requires.append(
                    f"volume: {line.component_name} ({line.variant}) is driven by "
                    f"{line.volume_driver}, which intake did not capture — the line is excluded, "
                    f"not guessed")
                continue
            priced.append(CostLine(component=line.component, component_name=line.component_name,
                                   variant=line.variant, unit=line.unit, monthly=placed,
                                   volume_driver=line.volume_driver,
                                   volume=volume.get(line.volume_driver),
                                   source_line=line.source_line, note=line.note))
            if line.capex is None:
                uncapexed.append(f"{line.component_name} ({line.variant})")
            else:
                capex += line.capex

    monthly = ThreePoint(0.0, 0.0, 0.0)
    for line in priced:
        monthly = monthly + line.monthly
    if build is None:
        requires.append("build cost: no vendor quote or budget bucket was captured at intake")
    if gaps:
        requires.append(f"price catalogue: no line at the {envelope!r} envelope for {gaps} — "
                        f"raised as a gap flag to the Review Board")
    if uncapexed:
        requires.append(f"capex: the catalogue carries no one-off cost for {uncapexed}; the "
                        f"build cost from intake is the only capital figure")
    return CostModel(
        lines=tuple(priced), monthly=monthly,
        year_one=year_one_total(monthly, (build.amount if build else 0.0) + capex),
        gap_flags=tuple(gaps), build=build, requires_input=tuple(requires),
        sheet_version=sheet_version, design_version=design_version,
        caveat=CATALOGUE_CAVEAT, envelope=envelope, capex=capex)
