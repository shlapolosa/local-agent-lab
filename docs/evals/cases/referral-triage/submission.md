# Use case: urgent referral triage

## Problem

Referrals arrive from GPs as unstructured letters and faxes into a shared clinical inbox. A nurse
reads each one, decides urgency, assigns it to a specialty, and books an appointment slot. At
current volume the queue runs eleven days behind, and urgency is judged by whoever happens to pick
the letter up. Two-week-wait cancer referrals have twice been found sitting in the routine queue.

## What we want

An assistant that reads each incoming referral, extracts the clinical facts a triage decision needs
(presenting complaint, red-flag symptoms, comorbidities, medication), proposes an urgency band and
a specialty, and drafts the appointment booking. A nurse confirms or overrides every proposal
before anything is booked or communicated to the patient.

## Expected change

Median time from referral received to triaged falls from eleven days to under one. Every referral
carries a recorded reason for its urgency band. Red-flag symptoms are surfaced explicitly rather
than depending on who read the letter.

## Constraints

Patient-identifiable clinical data throughout. The booking system is the system of record for
appointments; the patient administration system holds demographics. No communication goes to a
patient without a clinician confirming it.
