"""Meeting knowledge: gated minutes becoming a concept-centred model."""
from lab.core.meetings.minutes import MinutesError, minutes_to_spec
from lab.core.meetings.model import Speaker, Speakers

__all__ = ["minutes_to_spec", "MinutesError", "Speaker", "Speakers"]
