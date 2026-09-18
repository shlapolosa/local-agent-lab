# Chat assistant that tells the time

We would like a small chat assistant. A person types a message such as "what time is it?" or
"what's the time in Dubai?" and the assistant replies with the current time. It reads the system
clock, works out the time zone the person asked about, and writes the answer back in the chat.

There is no clinical content, no patient, no record, no claim and no appointment. Nothing is
stored beyond the conversation itself. It exists as a NEGATIVE CONTROL for the capability matcher:
a healthcare capability map should return NOTHING for it, and anything it does return is a false
positive that would have justified work no one asked for.
