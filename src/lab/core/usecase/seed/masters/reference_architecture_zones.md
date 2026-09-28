# Reference architecture model — zones

**Artifact:** reference_architecture
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py
**Section:** zones

| id | label | sub | layer |
|---|---|---|---|
| ex | Experience & received agents | how people and received agents reach AI | Layer 1 |
| gw | Edge & AI gateway | every AI call passes the gateway and the sensitive-data decision | Layer 2 |
| ag | Agent plane | build · host · orchestrate · safeguard | Layer 3 |
| kn | Knowledge & semantic | ground | Layer 4 |
| tl | Tools, actions & integration | act | Layer 4 |
| mp | Model providers by residency | infer — in-region · sovereign · out-of-region | Layer 4 |
| dt | Data | store | Layer 5 |
| bn | Boundary — traditional systems | reached only by integration; not catalogued | Layer 5 |
| me | Model engineering | source · adapt · validate · operate | Layer 5 |
| sec | Security pillar | identity · secrets · egress · threat · data protection | Pillar |
| gov | Governance & assurance pillar | control · lifecycle · evaluation · evidence | Pillar |
| pf | Platform foundation | governed cloud foundation beneath every layer | Foundation |
