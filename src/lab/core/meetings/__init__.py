"""Meeting knowledge: gated minutes becoming a concept-centred model."""
from lab.core.meetings.minutes import MinutesError, minutes_to_spec
from lab.core.meetings.model import Speaker, Speakers
from lab.core.meetings.naming import named_minutes, transcript_for_people

__all__ = ["minutes_to_spec", "MinutesError", "Speaker", "Speakers",
           "named_minutes", "transcript_for_people"]
