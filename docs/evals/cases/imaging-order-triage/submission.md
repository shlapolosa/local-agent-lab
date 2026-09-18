# Use case: prioritising imaging orders and report turnaround

## Problem
Radiology receives more CT and MRI orders than it can read the same day. Orders arrive without a usable urgency, urgent findings sit in a queue behind routine ones, and clinicians phone to chase reports.

## For whom
Radiologists, radiographers, the ordering clinicians in the emergency department and outpatient clinics, and the patients waiting on a result.

## What the solution does
1. Reads each imaging order and its clinical indication as it arrives.
2. Assigns a priority from the indication, the patient's presentation and the ordering setting, and explains it.
3. Schedules the scan slot and reorders the reading worklist by that priority.
4. Screens completed images for findings that need a same-hour read and moves them to the front.
5. Notifies the ordering clinician when the report is signed and escalates a critical finding to a named person until it is acknowledged.
6. Tracks turnaround against the department's targets and reports where they are missed.

## Data
Imaging orders, modality worklists, prior reports, the critical-findings policy, department targets.

## Constraints
A radiologist signs every report; the solution never communicates a finding a radiologist has not signed. Priority rules are the department's own and reviewed quarterly.
