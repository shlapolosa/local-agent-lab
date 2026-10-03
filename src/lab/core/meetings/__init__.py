"""Meeting knowledge: gated minutes becoming a concept-centred model."""
from lab.core.meetings.minutes import MinutesError, minutes_to_spec
from lab.core.meetings.model import Speaker, Speakers
from lab.core.meetings import render
from lab.core.meetings.naming import Turn, named_minutes, turns

__all__ = ["minutes_to_spec", "MinutesError", "Speaker", "Speakers",
           "named_minutes", "Turn", "turns", "render"]
