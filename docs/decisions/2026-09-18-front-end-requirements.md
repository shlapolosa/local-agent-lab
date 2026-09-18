# Front end and intake packet — requirements captured, not yet planned

Stated by the user on 18 Sep 2026, to be planned once the current work closes. Written down with the
constraints already known from the code, so the plan that follows is short rather than exploratory.

## What was asked

1. **The Microsoft Form's fields become the trigger packet.** `workflow-mcp` accepts them on BOTH
   surfaces (MCP tool and REST). Expandable later — ROI and others — as extra context over and above
   the problem statement. A Copilot Studio agent solicits the answers so it can post a complete packet.
   Form: `forms.office.com/Pages/ResponsePage.aspx?id=1PQRuTDeX0CW6bscdz_i_0_2SF_UIRpBr-dyAmrqlO1UMzNLODBJVEtMNENENUJGREM3Q0RGOUcyRS4u`
2. **A Power Apps front end**, so end-to-end testing runs on real data.
3. **Two roles: admin and SME** (SME being architect and business).
   - **admin** loads and updates artifacts, which are then seeded and referenced. An uploaded artifact
     must satisfy a SCHEMA, so it stays consistent with what the agents expect.
   - **SME** validates a design, or approves a build.
4. **Not the existing approvals UI** — Power Apps, integrated with Entra ID.
5. **A dynamic SME view**: the whole process as a **vertical roadmap**. As a step runs, that step
   expands to show its input, its output and its gaps, with approve / amend / decline, and any
   artifact downloadable.

## What already exists (so the plan does not rebuild it)

- **The packet is mostly there.** `USE_CASE_SCREENING.inputs` already carries `intake`
  (`InputKind.MAPPING`) beside `submission`, `attachments`, `submitter` and `conversation`. A caller
  can post structured fields today; what is missing is that nothing DECLARES which fields, so a form
  or an agent has nothing to read and no way to be told it is incomplete.
- **The field set is already a published artifact** — `intake-fields`, retrieval `whole`, listing
  eight groups (effort table, quality baseline, sensitivity flags, avoided-cost citation, data
  maturity, investment, urgency, volume assumptions) with who consumes each. **But its `Fields`
  column is PROSE** ("Role, headcount, frequency per week, current minutes per instance…"), so it
  cannot render a form or validate a payload as it stands.
- **Approvals are already a governed tool surface.** `workflow-mcp` carries `approvals_list` /
  `approvals_get` / `approvals_decide` (`ApprovalTools`), granted separately for READ and WRITE, and
  `approvals_decide` REFUSES a blank actor and records the channel as `mcp:<channel>`. A Power App
  decides through this, with the signed-in human as actor — the path a Copilot Studio agent was
  already meant to use.
- **Entra roles exist**: `ApiRoles.Workflow.Submit`, `Approvals.Read`, `Approvals.Decide`, enforced
  at the GATEWAY (`gateway/custom_auth.py`) against a table in `lab.substrate.apipolicy`. Two SME
  roles and an admin role are rows in that table, not new machinery.

## The three real constraints

- **Typed fields have to live in the artifact, not the app.** "Expanded later to include ROI" must be
  a corpus publish, not a Power Apps change and not a code change — the standing rule on this project.
  So `intake-fields` grows a machine-readable field definition (name, type, required, group, help),
  and ONE generated schema then feeds the form, the connector's tool schema and the validator.
- **A Power App cannot publish an artifact.** The corpus publisher holds the Ed25519 signing seed
  (`var/run/reference_signing_key`, deliberately never in `.env` or `LAB_ENV`) and runs as an
  operator CLI. So "admin loads and updates artifacts" needs a staging path: the app uploads and
  validates against the schema, a human with the seed releases. Anything else puts a signing key
  behind a web form.
- **A large nested object is an unreliable tool argument.** Measured on this project (AF #2747):
  nested MCP parameters flatten to a bare `{"type":"object"}` and a big nested payload is emitted
  only stochastically. So the Copilot path wants FLAT intake keys, or an uploaded ref — not one deep
  object. The Power App, posting REST, has no such constraint.

## Open questions for the planning session

- Does the roadmap view need per-step progress as a step RUNS, or is per-step state at the two
  existing approval gates enough? There is no per-step streaming API today; `<process>_status`
  returns run status, and the record carries `pending_steps` and `defaulted_steps` after the fact.
  Live per-step expansion is a new surface, and it is the largest single item on this list.
- "Amend" is a third decision. `ApprovalDecision` today is approve / decline / update, where `update`
  means changes requested and leaves the request open — amend probably maps to it, but whether an SME
  edits the artifact or only requests a change is a governance question, not a UI one.
