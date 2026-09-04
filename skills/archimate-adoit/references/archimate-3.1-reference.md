# ArchiMate 3.1 Notation Reference

Distilled from `archimate-3.1-cheatsheet.pdf` (same directory — open it for the visual notation).
The engine (`scripts/archimate_engine.py`) validates element/relationship type names against this
vocabulary; use the exact spellings below (they are the Model Exchange `xsi:type` values).

## Framework grid — layers × aspects

Every element sits at a (layer, aspect) intersection. The layout engine ranks rows from this:
layers stack top→down, and within a layer: Service → Interface → Behaviour → Active structure →
Passive structure (services float above the components that realize them; data sinks to the bottom).

| Layer | Passive structure | Behaviour | Active structure |
|---|---|---|---|
| **Motivation** | — | Stakeholder, Driver, Assessment, Goal, Outcome, Principle, Requirement, Constraint, Meaning, Value | — |
| **Strategy** | — | Capability, CourseOfAction, ValueStream | Resource |
| **Business** | BusinessObject, Contract, Representation, Product | BusinessProcess, BusinessFunction, BusinessInteraction, BusinessEvent, BusinessService | BusinessActor, BusinessRole, BusinessCollaboration, BusinessInterface |
| **Application** | DataObject | ApplicationProcess, ApplicationFunction, ApplicationInteraction, ApplicationEvent, ApplicationService | ApplicationComponent, ApplicationCollaboration, ApplicationInterface |
| **Technology** | Artifact | TechnologyProcess, TechnologyFunction, TechnologyInteraction, TechnologyEvent, TechnologyService | Node, Device, SystemSoftware, TechnologyCollaboration, TechnologyInterface, Path, CommunicationNetwork |
| **Physical** | Material | — | Equipment, Facility, DistributionNetwork |
| **Implementation & Migration** | Deliverable | WorkPackage, ImplementationEvent, Plateau, Gap | — |
| **Composite/Other** | — | — | Location, Grouping, Junction (AndJunction / OrJunction) |

Standard layer fills (the engine applies these automatically): Motivation `#E6E6FA`,
Strategy `#F5DEAA`, Business `#FFFFB5`, Application `#B5FFFF`, Technology/Physical `#C9E7B8`,
Implementation `#FFE0E0`.

## Relationships

| Category | Type | Meaning / when to use | Direction (source → target) |
|---|---|---|---|
| Structural | Composition | part-of, existential (part dies with whole) | whole → part |
| Structural | Aggregation | groups, part exists independently | whole → part |
| Structural | Assignment | active element performs behaviour / is deployed on | performer → behaviour |
| Structural | Realization | concrete realizes abstract (component → service, process → service) | realizer → realized |
| Dependency | Serving | offers functionality to (was "used by") | server → served |
| Dependency | Access | behaviour reads/writes passive element (`accessType`: Read, Write, ReadWrite) | behaviour → data |
| Dependency | Influence | motivation influence, +/− modifier | influencer → influenced |
| Dynamic | Triggering | temporal/causal sequence between behaviours | predecessor → successor |
| Dynamic | Flow | transfer of information/value between behaviours | sender → receiver |
| Other | Specialization | is-a-kind-of | specific → general |
| Other | Association | any other relation | — |

Direction matters for layout: the engine enforces that whatever is **served or realized sits
ABOVE** its server/realizer (invariant H4) — this is what produces the canonical layered reading
with consumers at the top and infrastructure at the bottom.

## Modelling conventions used by this skill

- **Composition/Aggregation shown by nesting**, not by a drawn line, whenever the child is placed
  inside a container on the view (`auto_edges()` skips those automatically).
- **Interfaces are the access points**: every cross-boundary call goes through one. They render as
  small icons (lollipop form), not boxes.
- **Never collapse the aspects**: a service (the offer) is not the function (the work) is not the
  component (the doer) is not the interface (the access point).
