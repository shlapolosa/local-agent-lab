"""Step 23 — the cost model. A sub-workflow of seven sub-steps, three of them pure arithmetic.

Cost is the sum of the reference-topology tiles the design switched on, priced against a REFERENCE
price sheet rather than a live pricing query. That is deliberate and it is what makes estimates
comparable: two submissions costed a week apart against a moving price feed are not comparable, and
a portfolio you cannot rank is not a portfolio. The cost of that choice is that every line must
cite the sheet VERSION it came from — an estimate against a superseded sheet is wrong in a way that
is invisible without the stamp (CR-23, CR-24).

Two refusals carry most of the weight:

* **FR-32** — a resource matching no price line raises a gap flag. Never a proxy price: a proxy
  looks exactly like a real figure in the total and nothing downstream could tell them apart.
* **FR-34** — the build cost states its provenance as a vendor quote, a budget bucket or an
  estimate. An approver reads "quote" as a number somebody will be held to, so the three are not
  interchangeable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from lab.core.usecase import seed

__all__ = [
    "CostError", "CostLine", "CostModel", "Provenance", "BuildCost", "ThreePoint",
    "band_position", "build_cost", "cost_model", "parse_estimate", "price_lines", "year_one_total",
]

_NUMBER = re.compile(r"\d[\d,]*")
_ENVELOPE = ("low", "expected", "high")


class CostError(ValueError):
    """A figure was asked for that the sheet cannot honestly supply."""


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
    known: bool = True

    def __add__(self, other: "ThreePoint") -> "ThreePoint":
        return ThreePoint(self.low + other.low, self.expected + other.expected,
                          self.high + other.high, self.known and other.known)


@dataclass(frozen=True)
class CostLine:
    service: str
    unit: str
    monthly: ThreePoint
    banded: bool
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


# ---------------------------------------------------------------- reading the sheet

def parse_estimate(text: str) -> ThreePoint:
    """"~175" is a point, "~100–400" is a band, "Included" is nothing owed but still a line.

    Anything else refuses rather than reading as zero — a line nobody could price must not
    disappear into a total as free."""
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


def price_lines() -> tuple[CostLine, ...]:
    """The reference price sheet as typed lines, at the version the seed holds."""
    sheet = seed.artifact("price_sheet")["lines"]
    out: list[CostLine] = []
    for row in sheet["rows"]:
        service, unit, estimate, banded, *rest = (row + [""] * 5)[:5]
        if not service.strip():
            continue
        out.append(CostLine(service=service.strip(), unit=unit.strip(),
                            monthly=parse_estimate(estimate),
                            banded=banded.strip().lower().startswith("y"),
                            note=(rest[0] if rest else "").strip()))
    return tuple(out)


def band_position(point: ThreePoint, envelope: str) -> float:
    """Sub-step 23.3 — position a banded line within its band from the quality attribute envelope."""
    if envelope not in _ENVELOPE:
        raise CostError(f"{envelope!r} is not an envelope position; expected one of "
                        f"{list(_ENVELOPE)}")
    return getattr(point, envelope)


# ---------------------------------------------------------------- the arithmetic

def year_one_total(monthly: ThreePoint, build: float) -> ThreePoint:
    """Sub-step 23.6 — build cost plus twelve times the monthly run cost. Arithmetic only."""
    return ThreePoint(build + monthly.low * 12, build + monthly.expected * 12,
                      build + monthly.high * 12, monthly.known)


def build_cost(amount: float, provenance: Provenance) -> BuildCost:
    """Sub-step 23.5. The provenance is not decoration — FR-34 forbids presenting an estimate as a
    quote, and the only way to keep that true is to carry which one it is."""
    if not isinstance(provenance, Provenance):
        raise CostError("a build cost must state its provenance as a vendor quote, a budget "
                        f"bucket or an estimate; got {provenance!r}")
    return BuildCost(float(amount), provenance,
                     basis=f"build cost taken from the {provenance.value} captured at intake")


# ---------------------------------------------------------------- assembly

def cost_model(resources: Sequence[str], *, build: BuildCost | None,
               envelope: str = "expected", design_version: str = "") -> CostModel:
    """Sub-steps 23.1-23.7 — what the `valuation_cost` tool returns.

    `resources` is the list of reference-topology tiles the composed design switched on."""
    sheet = price_lines()
    by_service = {line.service.lower(): line for line in sheet}

    matched: list[CostLine] = []
    gaps: list[str] = []
    for resource in resources:
        line = by_service.get(resource.strip().lower())
        if line is None:
            gaps.append(resource)                # FR-32 — a gap flag, never a proxy price
            continue
        matched.append(line)

    monthly = ThreePoint(0.0, 0.0, 0.0)
    for line in matched:
        placed = band_position(line.monthly, envelope) if line.banded else line.monthly.expected
        monthly = monthly + ThreePoint(line.monthly.low, placed, line.monthly.high)

    requires: list[str] = []
    if build is None:
        requires.append("build cost: no vendor quote or budget bucket was captured at intake")
    if gaps:
        requires.append(f"price sheet: no line for {gaps} — raised as a gap flag to the Review Board")

    artifact = seed.artifact("price_sheet")
    return CostModel(
        lines=tuple(matched),
        monthly=monthly,
        year_one=year_one_total(monthly, build.amount if build else 0.0),
        gap_flags=tuple(gaps),
        build=build,
        requires_input=tuple(requires),
        sheet_version=str(artifact.get("_source", "")),
        design_version=design_version,
        caveat=str(artifact.get("_caveat", "")),
    )
