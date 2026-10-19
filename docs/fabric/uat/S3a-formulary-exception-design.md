# Formulary exception — design note

Most prescriptions are dispensed without intervention: the medicinal product on the prescription
item is covered, the pharmacy dispenses, and the audit event closes the loop.

A formulary exception arises when the prescribed medicinal product is not covered by the patient's
plan and the clinician judges that no covered alternative is clinically appropriate. Today the
pharmacy telephones the payer and the outcome is recorded nowhere we can audit.

We propose modelling the formulary exception as a step between the prescription and the dispense.
