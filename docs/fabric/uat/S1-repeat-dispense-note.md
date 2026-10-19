# Repeat dispensing — current behaviour

A patient with a long-term condition is issued a prescription by their clinician at the end of an
encounter. The prescription carries one or more prescription items, each naming a medicinal product
and a quantity.

The pharmacy receives the prescription through the integration interface. Each dispense is recorded
against the prescription item it fulfils, and an audit event records who dispensed what and when.
Where a prescription authorises repeats, the pharmacy dispenses against the same prescription on
each subsequent visit without a new clinician review.

Nothing in this note is new. It describes what the service does today, so that the exceptions
documented elsewhere can be read against it.
