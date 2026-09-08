"""Who may fund this — step 26b's routing.

The delegation-of-authority thresholds are one of the three artifacts NEITHER source supplies. That
makes this module's whole job the refusal: with no configured table there is no honest way to say
"a director may sign this", so it escalates and says why. Routing too HIGH wastes a board's time;
routing too LOW commits money nobody was authorised to commit, and produces no observable event
afterwards. Only one of those is recoverable.
"""
import pytest

from lab.core.usecase import authority


TABLE = ({"limit": 50_000, "authority": "delivery lead"},
         {"limit": 250_000, "authority": "director"},
         {"limit": None, "authority": "investment board"})


def test_a_figure_routes_to_the_lowest_authority_that_covers_it():
    assert authority.route(30_000, TABLE).authority == "delivery lead"
    assert authority.route(60_000, TABLE).authority == "director"
    assert authority.route(9_000_000, TABLE).authority == "investment board"


def test_a_figure_exactly_on_a_threshold_belongs_to_that_threshold():
    """An off-by-one here is a decision taken one level too low, which is the direction that
    matters. Stated explicitly because "up to and including" and "under" both read naturally."""
    assert authority.route(50_000, TABLE).authority == "delivery lead"


def test_with_no_configured_table_it_escalates_rather_than_guessing():
    """The thresholds are local policy and nobody has set them. Inventing a plausible one would
    route a real decision by a number this lab made up."""
    out = authority.route(30_000, ())
    assert out.escalated is True
    assert "no delegation-of-authority" in out.reason
    assert out.authority == authority.UNSET


def test_an_unknown_investment_escalates_too():
    """A cost model that could not be computed leaves no figure to route on. Defaulting to the
    lowest authority would fund the cases we understand least."""
    out = authority.route(None, TABLE)
    assert out.escalated is True and out.authority == "investment board"
    assert "no year-one figure" in out.reason


def test_a_table_with_no_open_top_band_refuses():
    """Every table must say who signs for the largest amount. A table whose bands run out silently
    would leave the most expensive case unrouted."""
    with pytest.raises(authority.AuthorityError):
        authority.route(10_000, ({"limit": 50_000, "authority": "delivery lead"},))


def test_the_bands_must_be_ordered_and_distinct():
    with pytest.raises(authority.AuthorityError):
        authority.route(10_000, ({"limit": 250_000, "authority": "director"},
                                 {"limit": 50_000, "authority": "delivery lead"},
                                 {"limit": None, "authority": "board"}))


def test_an_open_condition_escalates_one_level_but_never_below():
    """FR-37d — a case carrying an unresolved marker is not one a delegated signer should close
    out. It goes up, and a case already at the top stays there."""
    assert authority.route(30_000, TABLE, open_conditions=["build cost unknown"]).authority \
        == "director"
    assert authority.route(9_000_000, TABLE,
                           open_conditions=["build cost unknown"]).authority == "investment board"


def test_an_escalated_decision_says_so_in_words_a_person_can_act_on():
    out = authority.route(30_000, TABLE, open_conditions=["build cost unknown"])
    assert out.escalated is True
    assert "build cost unknown" in out.reason
