# Use-case intake (CAFÉ)

*Feature notes split out of the root `CLAUDE.md` on 4 Oct 2026, verbatim. Shared rules (method, quality bar, invariants, cloud shape, identity, gateway, approvals, observability) stay in the root file.*

**The use-case workflow grows ONE ArchiMate model, step by step, and its views are projections of
it (14 Sep 2026).** After every step is recorded — the agent steps and the governed derivations
alike — a deterministic MAPPER (`lab.workloads.usecase.mappers.MAPPERS`, keyed by step KEY, one
entry per step) writes that step's output onto `lab.workloads.usecase.model.Model`: the frame as
motivation, step 4's elements as actors/functions/objects, the coverage match as capabilities
realised by functions, the workflow graph as processes (`bp-<node id>` — the ONE element steps 10,
15, 17, 18 and 19 all land on, because they share the node id), obligations as constraints, the
composition as family groupings carrying the CAFÉ archetype, step 21's components as
ApplicationComponents tagged `cafe.zone`/`cafe.families` from the pinned catalogue. Ids are a pure
function of the output (`ids.slug`, prefixed by kind) so a re-run UPDATES; every relation is checked
against the published matrix (`relrepair.check`) at proposal and an illegal one is COUNTED under
`dropped`, never raised — a mapper is bookkeeping and must not fail a 20-minute run (`mappers.apply`
restores the model and records the failure on it if a mapper throws). The model rides the process
records (`screening.json["model"]`, `design.package.json["model"]`) — no contract change — and the
design re-records it into its own package. A later step reads it as `model_summary` (names by
type, plus the composition's required families and which are realised), NEVER the spec: `message()`
dumps a context entry whole. Consequences: **the composition (22) now runs BEFORE step 21** (its
inputs are 17/19/20), so the selector is held to the families by a SOFT rule
(`steps._families_realised`, `Step.soft`, `gates.run_gated(soft=)`: asked for once on the retry,
then RECORDED under `unresolved` rather than raised — a family nobody selected is something the
design owes, which a reviewer must see, not a reason to lose the run; a catalogue with no
`families` column makes no claim, and that column is authored content still to publish). At the END
of the design `render_views` stores the model by ref (`design.model.json`) and projects it twice —
`archimate_render` (XML + one SVG per standard view) and the new semantic-mcp
**`semantic_render_cafe`** (`lab.substrate.mcp.semantic.cafe`: ours only, `include_comps:
["none"]`, every component in the CAFÉ zone its property names, on the archetype the composition
put on the root; a component with no zone is `unplaced`, never guessed; the skill's engine is
imported from `config.SKILLS_DIR` via `sys.path`, the one such seam) — refs into the package, SVGs
onto the conformance approval as tabs, and **`architecture_ref` is the draw.io file** (the model
when nothing drew, the package as a last resort). Neither render tool is REQUIRED: a design that
cannot draw is still a design, and the warning it records is the visible degradation.
**A step that answers for SOME of the workflow is the dangerous shape (15 Sep 2026).** Run 5 returned
ONE facet vector for a ten-node graph: it validated, it derived cleanly, and the exposure, the
obligations and the composition all came back describing that single node with max exposure 0 — a
control set nine steps short that looks exactly like a complete one. `steps._covers_every_node` now
holds steps 15 and 17 to the node ids the graph in their context carries: every node exactly once,
no id the graph does not have (a readiness EVIDENCE record spells `nodes` as a count, so a non-list
makes no claim). Two sibling rules, from the same run: a coverage map in which NO match is a
`lookup` must say so in a gap flag — the confidence is never forced up, the map is made to state
what it is — and step 21 carries a second SOFT rule, `_does_the_work`: a selection drawn entirely
from the cross-cutting zones (`ident`, `obs`, `plat`) is a control plane with nothing inside it,
recorded under `unresolved` rather than failing the run. Zones are the catalogue's own column, so it
asks nothing the corpus does not already say.

**The CAFÉ view reuses the reference architecture's OWN component ids** (`cafe.catalogue()`, matched
on normalised name): our corpus components were extracted from the artifact the skill draws, so a
selected component is usually the catalogue's own under the same name, and that is what lets the
published edges between two selected components survive `include_comps: ["none"]`. Run 5 drew
fifteen tiles and no lines because every id was minted; the same model now draws five. A minted id
(and its M4-extension warning) is left only for what the reference architecture does not carry, and
a view with tiles but no connections says so in a warning rather than passing as an architecture.

**THROWAWAY test aid, on by `USECASE_MODEL_TRACE=true`** (`lab.workloads.usecase.modeltrace`, one
module, one call in `modelling.grow`): every step that touched the model also stores and renders
its DELTA (touched elements + the step's relations + their endpoints, one view), and both approvals
show one tab per step in run order — "for the sake of proving the outputs of each step". Off by
default (one store + one render per step); `model_trace` never enters a prompt.

**A screening step whose tenant corpus is unpublished records a DECLARED default (13 Sep 2026).**
Steps 6, 8 and 11 read corpora this tenant does not have (the as-is landscape, the business service
levels, the source classification). Rather than stay pending and fail readiness gate C on every case,
each records the conservative reading of not knowing — `lab.workloads.usecase.fallbacks`: nothing is
realised, no service level is committed, every source contracted at the tightest classification —
validated and gated exactly like an answer, and listed under `defaulted_steps` on the screening
record and as `screening_defaulted_steps` on both design summaries. Defaulted is neither derived nor
pending: a reader can see exactly which findings rest on an assumption. A published corpus gets the
agent's grounded answer with no change. The full chain ran in the cloud on one submission that day:
screening → criticality approval → design (proceed) → conformance approval → investment (escalated:
no delegation-of-authority table) → authorisation approval → provisioning (6 work items, staged).

**A workflow graph is a DECOMPOSITION, and family membership is DERIVED (15 Sep 2026).** Two more
run-8 findings. Step 10 returned ten nodes for ten functions, each node wearing its function's own
name — and since the determinism tier, the facet vector, the exposure and the control set are all PER
NODE, the whole risk chain came out exactly as coarse as the inventory it copied while looking like
analysis. The prompt had literally asked for it ("one step per business function"); it now asks for a
split wherever the ACTION changes (retrieving is not interpreting, interpreting is not deciding), and
`steps._decomposes` refuses a graph whose every node is a function renamed, one-for-one. A function
that genuinely is one step stays one node — what is refused is EVERY function being one.
And step 21's family rule no longer waits on an authored column the reference architecture does not
have: `lab.workloads.usecase.families` follows the published chain **family → guardrail (the
composition's own enforcement map) → capability (`guardrails.cap`) → components
(`ai-capability-map.components`)**, recorded before step 21 so the architect sees what each component
would satisfy and the gate holds the selection to it. It is PARTIAL by nature — ten of twenty-six
guardrails name a capability — so `unclaimed()` names the families the corpus is silent about and the
rule demands nothing for them; a published catalogue column, if a tenant ever writes one, is believed
over the derivation. On run 8's real design: five families carried, six unclaimed, none uncovered.
The cost headline now carries `components_priced` beside `components`, because a year-one figure that
priced five of sixteen and says so is evidence, and one that does not is the empty summary again.
