# Speech & speaker-recognition provider — RFx question set

**Scope:** transcription of recorded meetings (and later live), **Arabic–English code-switching**,
speaker diarization, **speaker identification by voiceprint**, and optional English rendering — for a
UAE health-sector organisation (DOH Abu Dhabi context).

**Tags:** **[M]** mandatory, pass/fail · **[S]** scored · **RFI** asked at capability stage ·
**RFP** asked at commercial/contract stage. Untagged questions are scored and asked in both stages.

**Why these questions are pointed.** Our proof of concept (Sep–Oct 2026) found five failure modes that
generic RFx templates miss:
1. **transliteration** — Arabic speech written in Latin letters, or English in Arabic letters;
2. **silent omission** — the incumbent transcript dropped the Arabic sentence entirely;
3. **repetition loops** — one engine output the same word 80 times;
4. **language-switch read as a speaker-switch** in diarization;
5. **diarization labels that mix people** — about half the words in one meeting were attributed to the
   wrong person.

---

## 1. Company & fit — RFI

1. Legal entity, ownership and headquarters. Is there a **UAE-registered entity** that can contract? [M]
2. Name UAE and GCC customers in **healthcare or government** we may contact as references (minimum two).
3. What is your core product: your own models, a resold third-party model, or an orchestration layer? Name every underlying model and who owns it.
4. Headcount in research, engineering and support for **Arabic** specifically, and where they are based.
5. What is your financial runway or profitability, and your approach to continuity? Is source or model escrow available?
6. What does your 12–24 month roadmap say about Arabic dialects, code-switching, diarization and speaker identification?

## 2. Transcription (ASR) — functional

7. Which Arabic varieties do you support? Name each: **Gulf/Emirati, Levantine, Egyptian, Maghrebi, MSA**. Which have **dedicated** models? [S]
8. Do you transcribe **mid-sentence Arabic↔English switching** as spoken, without translating or transliterating the switched span? Show this on audio you supply. [M]
9. Do you return the **recognised language per segment or per word**? [M]
10. How is each language **scripted** in the output (Arabic in Arabic script, English in Latin)? Can this be configured? Do you ever transliterate, and is that flagged?
11. How do you detect and prevent **hallucination**: repeated tokens, invented text in silence, and dropped speech? Is any of it flagged in the output? [S]
12. Can custom vocabulary (names, clinical and organisational terms) be used **together with** code-switching mode? Some providers make the two mutually exclusive. [S]
13. Do you return **word-level timestamps and confidence scores**?
14. What are your limits on maximum file length and size? Can you ingest **video containers** (MP4) directly?
15. Which modes do you offer: batch, near-real-time and streaming? What latency does each have, and how do they differ in language and diarization support?
16. How do you handle **numbers, dates, medication names and acronyms** in each language? Do you do inverse text normalisation?
17. Do you offer an **English rendering** of Arabic speech? Is it delivered alongside the verbatim transcript, with alignment between the two?
18. Do you support punctuation, casing and paragraphing in Arabic?

## 3. Diarization — functional

19. Do you accept a **speaker-count hint**, either exact or as a minimum and maximum?
20. What diarization accuracy do you achieve on **in-person meetings recorded on one far-field microphone**, measured as speaker-attributed WER and not DER alone?
21. How do you avoid treating a **change of language as a change of speaker**? [S]
22. How do you handle **overlapping speech**? Is it marked?
23. Are speaker labels **stable across chunks** of a long recording? (Relevant where audio over roughly 60 minutes must be split.)
24. Do you avoid creating a speaker from **non-speech** (silence, breathing, keyboard noise)?
25. What is the maximum number of speakers, and how does accuracy degrade above five?

## 4. Speaker identification / voiceprints — functional

26. Do you offer **speaker enrolment and identification**: a stored voice profile matched automatically to diarized speakers? [S]
27. How much enrolment audio is needed, and can enrolment come from **real meeting audio** rather than a scripted session?
28. Do you return a **match score** for each speaker? Is there **open-set rejection**, meaning you report "unknown" rather than naming the nearest stored voice? [M]
29. How accurate is identification **across languages** (enrolled in English, speaking Arabic)?
30. **Where are voiceprints stored?** Can we hold them ourselves, either as exportable embeddings or as profiles in our own tenant? [M]
31. Are voiceprints **portable**? What format, and are they tied to a specific model version? What happens to stored profiles when your model changes, and is re-enrolment needed?
32. Do you provide APIs to **delete a voiceprint** with confirmation, and to list all voiceprints held for an individual? [M]
33. Do you provide tooling or metadata for **consent capture and audit**: who attested consent, and when?
34. What false-accept and false-reject rates do you achieve at your recommended threshold? Name the evaluation set.

## 5. Accuracy evidence & evaluation — RFI

35. Provide benchmark results on **Arabic–English code-switched** audio. Name the dataset and whether it is public or independent.
36. Will you join a **bake-off on our audio** (under NDA, in-country processing) at no cost? [M]
37. Report WER **and** script mix (the share of Arabic script), coverage (words returned compared with a reference), and speaker-attributed WER. We do not rank on WER alone, because it scores correct transliteration as an error.
38. Is output **deterministic**? How much does the transcript vary across repeated runs on identical audio?
39. Do you have results on **noisy, reverberant, in-person** recordings rather than clean telephony?

## 6. Non-functional

40. What is your processing speed (real-time factor) for batch, and your guaranteed turnaround per audio hour? [S]
41. What are your concurrency and rate limits, and how do they change by tier?
42. What availability SLA do you offer? How is it measured, and what service credits apply? [S]
43. Do you offer **asynchronous jobs with webhooks**, and idempotent retries?
44. How do you manage API versioning? **Can a model version be pinned**, and how much notice do you give before a deprecation or behaviour change? [M]
45. When you update a model, how do you test for regressions on Arabic and code-switched audio? Do you publish change logs?
46. What are your support hours in **UAE time (GST)**? Is support available in Arabic? What are your severity levels and response times?
47. Which observability features do you provide: request IDs, usage reporting, a status page?

## 7. Deployment — hosted and self-hosted

48. **SaaS:** in which regions is audio **physically processed** (inference executed, not just provisioned)? Is there a **UAE region**, and on which provider (Azure UAE North or UAE Central, AWS me-central-1, Core42/G42, other)? [M]
49. Do you offer a single-tenant or dedicated deployment, and in which UAE region?
50. Do you offer **self-hosted or on-premises** delivery as containers or Kubernetes? Can it run on Azure Container Apps or AKS? Is an **air-gapped** option available?
51. What hardware does self-hosting need: GPU model and count, a **CPU-only** option, RAM, and throughput per node?
52. For self-hosted deployments, how are models, security patches and licences delivered and activated **offline**?
53. Are SaaS and self-hosted at **feature parity**: dialects, diarization, speaker identification, translation? List the differences.
54. Does self-hosted software send any outbound connection (telemetry, licence check)? Can it be fully disabled? [M]

## 8. UAE regulatory, privacy & data handling — RFP

55. How do you comply with the **UAE PDPL** (Federal Decree-Law 45/2021)? Do you accept the role of **processor** under our data processing agreement? [M]
56. Can you comply with **Federal Law 2/2019 (ICT in health fields), Article 13**: health data processed and stored **inside the UAE**? [M]
57. Can you align with **DOH Abu Dhabi ADHICS** and the **UAE Information Assurance** standard? Provide evidence or a gap list.
58. Voiceprints are **biometric (sensitive) data**. What specific controls apply to them: separation, encryption, access, retention? [M]
59. Where does each of the following reside: **audio, transcripts, voiceprints, logs, backups and support copies**? Do any leave the UAE, including during support or debugging? [M]
60. Do you use customer audio or transcripts to **train or improve models**? Is the default **opt-out by contract**? [M]
61. List all **sub-processors** with locations, and describe how you notify us of changes.
62. What is the retention period for uploaded audio and outputs? Is **deletion immediate on request**, and do you provide a deletion certificate? Do you ever return a **public URL to our audio**? [M]
63. How do you handle law-enforcement or foreign-government access requests, and what are your notification obligations?
64. Which governing law and jurisdiction apply (UAE onshore, ADGM, DIFC)? Do you have a local contracting entity?

## 9. Security

65. Certifications: **ISO 27001**, 27701, 27017/27018, SOC 2 Type II. Provide current reports. [S]
66. What encryption do you use in transit and at rest? Do you support **customer-managed keys** (BYOK or HSM)?
67. Do you offer private connectivity (Private Link, VNet injection, IP allow-listing)? Can public endpoints be disabled?
68. Which identity integrations do you support (**Entra ID SSO**, SCIM, RBAC, service principals, short-lived tokens)?
69. Can audit logs be exported to our SIEM? Which events are logged?
70. Provide your last independent **penetration test** summary, and describe your vulnerability disclosure process.
71. What is your **incident notification** timeline (we need 72 hours or less) and process? [M]
72. How do you secure the model supply chain: model provenance and integrity of model weights?

## 10. Responsible AI

73. What is your measured accuracy **by dialect, accent and gender**? What bias mitigation do you apply?
74. Is silent output a possibility? How do you **signal missing or low-confidence spans**, so that a fluent transcript cannot hide dropped speech? [S]
75. How do you make it clear in the output whether a span was **transcribed or translated**?
76. Can match scores and outputs be explained to a non-specialist reviewer?

## 11. Integration

77. Which APIs do you offer (REST, gRPC, WebSocket)? Which SDKs (Python required)? Is OpenAPI documentation available?
78. Which output formats do you support (JSON segments with speaker, language, timing and confidence; VTT; SRT)? Are schemas published and versioned?
79. Do you have ready integration with **Microsoft Teams, Graph or SharePoint** recordings, Power Automate, or the Azure Marketplace?
80. Is a **sandbox** environment available, with test credits?
81. Do you support passing audio by reference (a signed URL to our store) rather than by upload?

## 12. Commercial & licensing — RFP

82. **SaaS pricing per audio hour**, broken down for batch versus real-time and for diarization, speaker identification, translation and custom vocabulary as add-ons.
83. Do you charge for **voiceprint storage** or per identification?
84. **Self-hosted licensing:** what is the metric (per node, GPU, core, audio hour or user)? Give the annual cost and what is included (updates, support).
85. What are your volume tiers, minimum commitments and overage rates? How long are prices locked?
86. Quote in **AED or USD**. Include VAT treatment and payment terms.
87. Is the service eligible for **Azure consumption commitment (MACC)** or marketplace billing?
88. What are your support tiers and their costs?
89. Will you provide free **POC/bake-off credits** for the evaluation? [S]
90. Provide the **total cost of ownership over 3 years** for 50 / 200 / 1,000 meeting-hours per month, both SaaS and self-hosted.

## 13. Exit & portability — RFP

91. How do we export all transcripts, metadata and **voiceprints** at termination, and in what formats? [M]
92. Will you certify deletion of all our data, including backups, at termination? [M]
93. How long is the notice period for discontinuing the product or a model, and what transition support do you provide?
94. Do you offer escrow for self-hosted software and models?

---

## Proposed scoring (adjust before issue)

| Area | Weight |
|---|---|
| Arabic–English accuracy on **our** bake-off audio (script mix, coverage, speaker-attributed WER) | 30 % |
| Diarization and speaker identification on in-person audio | 15 % |
| UAE residency, regulatory and security fit | 20 % (any [M] failed = excluded) |
| Deployment flexibility (UAE SaaS and/or self-hosted parity) | 10 % |
| Commercials (3-year TCO) and licensing clarity | 15 % |
| Integration, support, roadmap and vendor viability | 10 % |
