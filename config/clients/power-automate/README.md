# Power Automate: a saved meeting recording becomes a transcript, and the meeting hears back

This folder holds a client template for a Power Automate cloud flow that watches for a Teams meeting
recording landing in OneDrive, starts the lab's `meeting_to_transcript` process, waits for it to
produce its question, asks that question in Microsoft Teams as an Adaptive Card, and sends the
person's answer back. Approving the answer starts the minutes run inside the lab; the flow does not
start it and its credential deliberately cannot.

The flow is four ordinary HTTP calls and two connectors. It handles no tokens, holds no store
credentials, and never touches the recording's bytes — it passes two identifiers and lets the lab
fetch the file itself.

Read `../README.md` first for the client convention this folder follows: committed templates carry
`${GATEWAY_URL}` and `${ENTRA_GATEWAY_AUDIENCE}` placeholders, and the two values that change per
deployment live only in `.env`.

## Files

`flow.template.json` is the flow described by most of this document: a recording becomes a run, and a
question reaches a person.

`notify.template.json` is a **second, much smaller flow** going the other way — the lab pushes to it
when a minutes run has written its outputs back into the tenant, and it posts a message in the
meeting's own chat. It is described in *The second flow* at the end of this document. The two are
separate flows on purpose: one is triggered by a file appearing and the other by the lab, they fail
for unrelated reasons, and neither should be able to stop the other.

`flow.template.json` is a Logic Apps workflow definition — the `triggers` and `actions` of the flow,
in the schema Power Automate itself stores. It is a working starting point to adapt in the designer,
not a signed solution package; see *Getting the definition into Power Automate* below.

Everything you must supply yourself appears as `<<A PLACEHOLDER IN DOUBLE ANGLE BRACKETS>>`. The
client secret is one of them and it stays one: it is typed into the designer, and no real secret ever
goes into this file or any other committed file.

## Rendering the placeholders

```bash
./lab.sh clients          # also runs on `./lab.sh up`
```

That writes `flow.json` beside the template, substituting six values from `.env`:

| Placeholder | From | What it is |
|---|---|---|
| `${PUBLIC_GATEWAY_URL}` | `.env` | the gateway's **internet-reachable** address. Not `GATEWAY_URL`: the flow runs in Microsoft's cloud and can never reach `127.0.0.1`, so this is a separate setting rather than an override — both are true at once |
| `${ENTRA_GATEWAY_AUDIENCE}` | `.env` | the lab-gateway application ID URI |
| `${ENTRA_TENANT_ID}` | `.env` | the tenant the token comes from |
| `${CONNECTOR_CLIENT_ID}` | `provision_connector_identity.py` | this flow's app registration |
| `${ORGANISER_DRIVE_ID}` | `collab_user_drive` | the organiser's OneDrive |
| `${ONEDRIVE_RECORDINGS_FOLDER_ID}` | `collab_list` | the Recordings folder inside it |

Every one is an address or a **public identifier** — never a credential. That is the rule the render
step is held to (`tests/governance/test_lab_sh_renders_clients.py` fails if a name matching
`SECRET|PASSWORD|_KEY|TOKEN` is ever added to the substitution list), which is why a rendered file is
safe to sit on disk and paste around.

**One placeholder is deliberately left**: `<<FLOW_APP_CLIENT_SECRET>>`. Type it into the Power
Automate designer; it goes nowhere else, in no file, ever.

Rendered `*.json` under `config/clients/` is git-ignored and the `*.template.json` files are not, so
regenerating is free and committing a rendered copy is not possible by accident.

The same test also pins the two ways this used to break silently: the glob missing a template whose
filename is not `settings.template.json` (which is exactly what happened to this file), and a
placeholder added to a template with no matching substitution — which renders the literal string
`${NAME}` into an `audience` or a `tenant`, a value that looks almost right and fails to
authenticate.

---

# What the flow does

## 1. The trigger: a recording is saved

Teams saves a **non-channel** meeting recording to the OneDrive of the person who started the
recording, in a folder called `Recordings`. The flow uses the OneDrive for Business trigger **"When
a file is created (properties only)"** (operation `OnNewFilesV2`) pointed at that folder.

Use the *properties only* variant, not plain "When a file is created" (`OnNewFileV2`). The plain one
downloads the file into the flow and **skips every file larger than 50 MB**, which is every meeting
recording that has ever existed. It is also the wrong shape for this design: we want the item's
identifiers, never its bytes.

Microsoft's own connector documentation warns that the OneDrive "on new file" triggers can fire more
than once for a single change and can misbehave when more than roughly thirty changes accumulate
between polls. Two defences are in the flow. A condition drops anything that is not a video (the
`Recordings` folder also collects `.vtt` transcripts and thumbnails), and the submit call carries an
`idempotency_key` — see step 2.

**A channel meeting saves somewhere else.** Its recording goes to the *Recordings* folder of the
channel's document library on the team's SharePoint site, not to anybody's OneDrive. To cover those,
duplicate the flow and swap the trigger for the SharePoint connector's **"When a file is created
(properties only)"**, pointing it at the site and library. Two things then change downstream. The
drive id is the document library's drive, not a person's OneDrive, so the `driveId` variable becomes
the library's drive id — same handle shape, different value. And `owner` can no longer come from
"Get my profile": nobody's personal drive is involved, so the organiser must come from the meeting
itself or from a lookup you add. The lab wants a human who was actually in the meeting and who can
recognise the voices; a shared mailbox or a service account is not an acceptable substitute.

The trigger returns a list, and Power Automate's split-on setting turns each file into its own flow
run. The template sets `"splitOn": "@triggerOutputs()?['body']"`. The designer normally fills this in
for you — check it after import rather than trusting the template, since the exact split-on path is
one of the things I could not verify against a live tenant.

## 2. Start the run

```
POST ${GATEWAY_URL}/api/processes/meeting_to_transcript/runs
Content-Type: application/json; charset=utf-8

{
  "owner": "maria@contoso.com",
  "recording": "collab://item/<driveId>/<itemId>",
  "requester": "power-automate",
  "idempotency_key": "<itemId>"
}
```

The response is **202** with `{"request_id", "process", "status", "accepted", "duplicate", "lanes", "poll"}`.
It is not a finished run and never will be: transcription takes minutes, so the process is
asynchronous by contract and the submit call only acknowledges.

**One submit can be several RUNS.** When the deployment sets `SPEECH_LANES`, the lab starts one run
per speech provider — the same recording transcribed by each, so their transcripts can be compared —
and `lanes` lists them as `[{provider, request_id, duplicate}]`. `request_id` is the FIRST lane, kept
so a flow written before lanes existed still works; a lane that could not be submitted has an empty
`request_id` and carries its own `error` instead.

The flow therefore loops over `lanes` and does steps 3 to 5 once per lane, which is what asks about
all of them. Polling `request_id` alone asks about the first lane and silently ignores the rest — and
if that first lane fails, asks nothing at all. Measured live on 8 Sep 2026: three lanes, the first
two failed on a provider error, and the third finished with a perfectly answerable question that
nobody was ever shown, because the flow had already terminated on the first.

Three properties of that loop are not obvious and each is silently wrong rather than loudly broken:

- **Sequential, not concurrent.** Power Automate refuses `SetVariable` inside a concurrent
  Apply-to-each, and `runState` is set on every pass. The template sets concurrency to 1.
- **`runState` is RESET at the top of each lane.** Otherwise the Do-Until's condition is already
  satisfied by the previous lane's `done`, the loop exits before the new run has started, and the
  card asks the previous lane's question again — a wrong answer that looks entirely normal.
- **No `Terminate` inside the loop.** A lane that fails, an ambiguous answer, a refused decision:
  each records itself in a `problems` array and the loop carries on. Terminating would abort the
  flow and take the healthy lanes with it, which is the fault the loop exists to remove. After the
  loop, the flow fails only when EVERY lane failed, with all the reasons in the message.

Inside the loop use `items('For_each_lane')` for the lane and `item()` for a Select's own element —
a Select rebinds `item()`, so the two are not interchangeable.

**`owner`** is the meeting organiser's user principal name — the person who will be asked to identify
the speakers. The flow takes it from the Office 365 Users action **"Get my profile (V2)"**, which
returns the owner of the *connection*, i.e. the person whose OneDrive is being watched. Be aware of
the seam: Teams saves a recording to the drive of whoever **started the recording**, who is usually
but not always the organiser. Either way that person was in the meeting and can recognise the voices,
which is what the field is for. If you ever run this flow under a service account, "Get my profile"
becomes wrong and you must source the organiser some other way.

**`recording`** is a handle of exactly the form `collab://item/<driveId>/<itemId>`. It carries two
identifiers and nothing else — never a URL, never a download link, never a sharing link. The lab
refuses a handle containing `/`, `?`, `#` or whitespace precisely so that a pre-signed download URL
cannot be smuggled into one: such URLs leak into logs and traces and are stale by the time anything
uses them. The workload passes the handle to the collaboration port, which streams the recording into
the lab's own governed store and hands back an internal reference.

The item id comes straight from the trigger (`Id`). **The drive id does not** — the OneDrive
connector's file metadata has no drive id, and its `FileLocator` field is an opaque connector token,
not one. Since the drive here is one fixed person's OneDrive, the id is a constant: the template puts
it in a variable, `driveId`, for you to fill once. Three ways to get it:

- Sign in as that person at Graph Explorer and call `GET /me/drive?$select=id`.
- Call Microsoft Graph `GET /users/{upn}/drive?$select=id` with any credential that may read it.
- Ask the lab. Its collaboration port lists drives and mints these handles already
  (`collab_drives`, `collab_list`, `collab_recordings`), and a listing hands back the finished
  `collab://` string — which is the shape this flow is reproducing by hand.

If you would rather resolve it per run than paste a constant, add a Graph HTTP call before the submit
using the same Active Directory OAuth authentication with `audience` set to
`https://graph.microsoft.com`. That means granting the flow's app registration Graph permissions,
which widens a credential whose whole appeal is that it can do exactly one thing. The constant is the
better trade.

**`idempotency_key`** is the file's item id. If the OneDrive trigger fires twice for one recording,
the second submit returns the *same* `request_id` with `duplicate: true` instead of queueing a second
transcription. The flow does not branch on `duplicate` — it polls the returned `request_id` either
way, which is correct, because a duplicate is the same run. The de-duplication window is 24 hours;
after that the same key starts a new run. It is a retry window, not a uniqueness constraint.

**A 422** comes back with a readable `error` sentence *and* an `expected` object describing every
input the process accepts, keyed by field name. The flow catches the failure (a Terminate action
whose `runAfter` is `Failed`) and puts both into the flow's failure message, so the run history shows
what the process actually wanted rather than a bare status code.

## 3. Poll until the question exists

```
GET ${GATEWAY_URL}/api/processes/meeting_to_transcript/runs/{lane request_id}
```

Once per lane, inside the loop from step 2 — `items('For_each_lane')?['request_id']`, never
`body('Start_run')?['request_id']`, which is the first lane's and would make every pass poll the
same run.

A Do-Until loop: wait one minute, GET, store the body in a variable, repeat until `status` is `done`
or `failed`. The template caps it at 90 iterations and `PT1H30M`, which is generous for an hour of
audio and cheap, since polling costs nothing but flow actions.

When `status` is `done` the body carries `approval_id`, `review_app`, `transcript_ref`,
`recording_ref`, `speakers` and `summary`, alongside the run's own `request_id`, `trace_id` and
timestamps. When it is `failed` the `error` field is a sentence a person can read; the flow surfaces
it directly. Only fields that have values are present, so read everything with a null-safe `?[...]`.

Reaching the iteration limit without either status is not a failure of the run — the transcription may
still finish, and the question will then be waiting in the review app for the organiser. The flow says
exactly that in its failure message rather than pretending the work is lost.

## 4. Ask the human, in Teams

The flow uses **"Post adaptive card and wait for a response"** (operation
`PostCardAndWaitForResponse`), posted by the Flow bot into the organiser's chat with it. That action
exists so that a flow can ask a question in Teams without a bot registration, a Teams app package or
an inbound webhook, which is why it is the right instrument here.

The card loops over `speakers` from step 3. Each entry is `{label, seconds, turns, samples[]}`, and
each becomes a container showing the label, how long that voice spoke, how many turns it took, and its
sample utterances — the samples being the thing that actually lets a person tell one voice from
another. Under them sit two text inputs, `identity_<label>` and `tag_<label>`.

**Two inputs, exactly one filled.** A directory identity (an email or user principal name) is
preferred because it resolves to a real person later. The free tag exists because not everyone in a
meeting room is in your directory: guests, vendors, a partner's architect, a patient. Without the tag
you would either lose those speakers entirely or be pushed into inventing directory identities for
them, and an invented identity in a set of minutes is worse than an honest "the vendor's architect".
Both boxes filled is ambiguous, neither is unanswered, and the flow refuses both cases with a message
naming the offending labels rather than silently preferring one box. The approval stays open when it
does, so the organiser can still answer in the review app.

**On the Arabic.** Sample utterances may be in any language the meeting used, frequently Arabic, and
frequently Arabic and English in the same sentence. The card is therefore built as **objects** — a
Select action produces real JSON objects and a Compose assembles them — and serialized once with
`string()` at the moment it is handed to the Teams action. Never assemble card JSON by string
concatenation: you then have to escape quotes and newlines by hand, which is exactly where non-Latin
text gets mangled. For the same reason the answer object is built with `setProperty` rather than
concatenated, and nothing anywhere calls `uriComponent` or `encodeUriComponent` on a sample or a tag.
The one place the template does use `decodeUriComponent('%0A%0A')` is to make a blank line between
samples; it produces newlines and touches nothing else.

Two limits worth knowing before a real meeting hits this. A Teams message has a size ceiling (about
28 KB), so a meeting with many speakers and long sample utterances can produce a card too large to
post; if that happens, shorten or drop the samples for speakers past the first several. And an
Adaptive Card sent by these wait-for-response actions accepts **one** submission — the first response
continues the flow and any later one is ignored.

## 5. Send the answer back

```
POST ${GATEWAY_URL}/api/approvals/{approval_id}/decide
Content-Type: application/json; charset=utf-8

{
  "decision": "approve",
  "actor": "maria@contoso.com",
  "channel": "power-automate",
  "answer": {
    "SPEAKER_00": {"identity": "maria@contoso.com"},
    "SPEAKER_01": {"tag": "the vendor's architect"}
  }
}
```

Every label from `speakers` appears exactly once, each with exactly one of `identity` or `tag`. A
missing label, an extra label, or a label the approval did not ask about is refused with a sentence
saying which.

**`actor` is the real signed-in person who answered the card** — the flow reads it from the card
response's responder, and from nowhere else. There is deliberately no fallback and no default: not
the flow owner, not the connection owner, not a service account. Who identified these speakers is the
entire point of the audit record, and a blank actor is refused rather than defaulted. If your
responder field ever comes back empty, the correct outcome is the 422, and the flow surfaces it.

`decision` is one of `approve`, `decline` or `update` (`update` means changes requested and leaves the
request open). The template's card offers approve and decline. **A decline needs no answer** and the
flow sends none.

Approving is what starts the minutes run. That happens inside the lab, off the back of the approval
itself, because the approval is the only place that knows both the question and the transcript this
particular meeting produced. The flow must not try to start it, and the flow's credential — scoped to
the gateway audience and granted only what a triggering client needs — cannot.

---

# Setting up the app registration

The flow authenticates every gateway call with Power Automate's built-in **Active Directory OAuth**
on the HTTP action. That is a client-credentials grant the platform performs for you: you give it a
tenant, a client id, a secret and an audience, and it acquires and refreshes the token. The flow never
sees a token, never stores one, and has no expiry logic to get wrong.

In the flow definition it looks like this, and it is the same block on all four HTTP actions:

```json
"authentication": {
  "type": "ActiveDirectoryOAuth",
  "tenant":   "<<ENTRA_TENANT_ID>>",
  "audience": "${ENTRA_GATEWAY_AUDIENCE}",
  "clientId": "<<FLOW_APP_CLIENT_ID>>",
  "secret":   "<<FLOW_APP_CLIENT_SECRET>>"
}
```

`tenant` is `ENTRA_TENANT_ID` from `.env`. `audience` is `ENTRA_GATEWAY_AUDIENCE` — the lab-gateway
app's application ID URI, the same value Claude Code passes to `az account get-access-token`. The
gateway validates the resulting token against the tenant's JWKS, checks issuer and audience, and maps
it to a virtual key, which is where this client's grants, budget, metering and tracing come from.

**One script does all of this**, and it is idempotent:

```bash
set -a && source .env && set +a
.venv/bin/python scripts/provision_connector_identity.py
```

It adds the three `/api` app roles to the `lab-gateway` app (preserving the ones already there — a
`PATCH` of `appRoles` replaces the whole collection, so appending is not optional), registers
`power-automate-connector`, mints a secret, and grants it exactly:

| Role | What it opens |
|---|---|
| `Workflow.Submit` | start a run, and read the status of one |
| `Approvals.Read` | list approvals and read one in full, including its question |
| `Approvals.Decide` | record the person's answer |

It then prints `CONNECTOR_CLIENT_ID` and `CONNECTOR_CLIENT_SECRET` for `.env`, plus the
`ENTRA_CLIENT_TO_KEY` entry pairing the registration with the `POWER_AUTOMATE_KEY` virtual key —
without which the gateway validates the token and then refuses, because there is no key to meter the
call on. `CONNECTOR_CLIENT_ID` is the `<<FLOW_APP_CLIENT_ID>>` above; the secret is typed into the
designer and stored nowhere else.

Note what is **not** on that list. `Approvals.Ask` does not exist as a role at all — raising a
question is a workload's `approvals_ask` over MCP, so a connector cannot manufacture a question and
then answer it. And there is no role that would let this flow start `transcript_to_minutes`: that
process is declared `external=False` in `lab.platform.contracts`, so neither surface generates an
entry point for it and **no credential can start it, including the lab's master key**. The minutes run
begins only when the organiser's answer is approved. That is the one gate the meeting pipeline has,
and it is closed by the process's own declaration rather than by a permission somebody has to keep
granting correctly.

## How the check actually runs

The role is enforced at the **gateway**, in `src/lab/substrate/gateway/custom_auth.py`, against the
table in `src/lab/substrate/apipolicy.py` — not inside the front door. The reason is worth knowing if
you ever debug a 401: LiteLLM's pass-through sends the backend a *static* `Authorization` and drops
incoming headers that collide with it, so the front door receives only `accept`, `authorization` (a
shared secret), `connection`, `host` and `user-agent`. The caller's identity does not survive the hop.
Enforcing where the validated claims already exist needs no identity forwarding at all, and it is the
same place APIM's `validate-jwt` + `<required-claims>` will sit after the migration.

A refusal names the role it wanted and the roles the registration holds, because a missing
`appRoleAssignment` is the likeliest cause:

```
POST /api/processes/meeting_to_transcript/runs (processes.submit: start a run) requires the
'Workflow.Submit' app role; app registration <id> holds ['EA.Model', 'Tools.ADOIT']
```

A **virtual key cannot call `/api` at all** — it authenticates but carries no roles, so there is
nothing to authorise an operation against. The master key is excepted as the admin plane.

The audit trail then has two independent identities in it, and that is the design: the **application**
authorises the call, and the **person** named in `actor` authorised the decision. Neither substitutes
for the other.

---

# Verified against the live gateway

Every HTTP call in `flow.template.json` was exercised with the connector's own client-credentials
token on 5 Sep 2026, so what the flow sends is known to be accepted rather than assumed:

| Flow action | Call | Result |
|---|---|---|
| `Start_run` | `POST /api/processes/meeting_to_transcript/runs` | `202`, returns `request_id`; re-sending the same `idempotency_key` answers `duplicate: true` and queues nothing |
| `Get_run` | `GET /api/processes/meeting_to_transcript/runs/{id}` | `200`, carries `status` and `approval_id` |
| `Send_the_answer` | `POST /api/approvals/{id}/decide` with `answer` | `200`, records the responder as `actor` |
| `Send_the_decline` | `POST /api/approvals/{id}/decide` | `200` |

The decide calls were run against throwaway approvals, not a real one.

Two refusals were also confirmed, because they are the ones a flow author will hit:

- a **virtual key** on `/api` → `401` telling you to acquire an Entra token. The flow must use
  ActiveDirectoryOAuth; a pasted key will not work, by design.
- an Entra token **without `Workflow.Submit`** → `401` naming the role it wanted and the roles the
  app registration actually holds. That is almost always a missing `appRoleAssignment`; re-run
  `scripts/provision_connector_identity.py`.

---

# Getting the definition into Power Automate

`flow.template.json` is a workflow definition, not an importable `.zip` solution package, and Power
Automate does not accept a bare definition file through the "Import" button. Three ways to use it:

- **Build the flow in the designer** and use this file as the specification — every action's name,
  type, inputs, expressions and `runAfter` are here, and the section above says what each one is for.
  Slowest, but you see every connection get created properly.
- **Paste per action.** Create the trigger and each action in the designer, then use each action's
  *Peek code* view to check your inputs against this file's.
- **Round-trip through a solution.** Create a solution-aware flow with the right trigger and
  connections, export the solution, replace the definition in the exported package's flow JSON with
  this one (keeping the package's own `$connections` references, which are environment-specific), and
  import it back. This is the fastest path for repeat deployments and the one to use if you want this
  flow in source control as a package.

Whichever route you take, the connection references in the template are the generic ones
(`shared_onedriveforbusiness`, `shared_office365users`, `shared_teams`); the designer rewrites them to
your environment's actual connection names.

---

# Why not MCP

The lab's front door for business processes is an MCP server, `workflow-mcp`, and every process is
exposed there as generated tools. Power Automate cannot use it. MCP over streamable HTTP opens with a
session handshake and then answers over server-sent events, holding a stream open and delivering
results as events on it. Power Automate's HTTP action is a request/response instrument: it sends a
body, waits for a body, and hands you JSON. It has no notion of a session to establish, a stream to
hold, or events to consume, and the workarounds people build for this are uniformly worse than not
trying.

So the lab exposes the same processes over REST at `/api` for clients that are not agents. This is a
second adapter over the same port, not a translation layer: both surfaces validate against the same
process contract and call the same submit function, so idempotency, validation, the declared outputs
and the audit trail cannot drift between them. Agents and workloads keep using MCP; low-code flows,
web clients and scripts use REST.

---

# What I could not verify

I wrote this against the repository and against Microsoft's connector reference. I did not have a
Power Automate tenant, a Teams tenant or a running gateway to test against, so the following are
stated honestly as unverified.

**Whether `${GATEWAY_URL}/api/...` actually resolves.** The REST routes exist and are served by
`workflow-mcp` itself (`src/lab/substrate/mcp/workflow/rest.py`, mounted alongside `/mcp` on the same
port and behind the same bearer check). Reaching them *through the gateway* needs a pass-through, and
one is being added to `config/litellm-config.yaml` (`general_settings.pass_through_endpoints`,
forwarding `/api/...` to `WORKFLOW_API_URL` with `auth: true`) as this is written. Two things about
it to check before blaming the flow:

- The list at the time of writing covers `/api/processes`, `/api/processes/{process}/runs`,
  `/api/approvals` and `/api/approvals/{approval_id}/decide`. It does **not** yet cover
  `/api/processes/{process}/runs/{request_id}` — which is the URL step 3 polls, on every iteration of
  the Do-Until loop. Unless the pass-through matches it by prefix, the poll will 404 and the flow will
  spin until its limit. If that is what you see, that route is the thing to add.
- `workflow-mcp` sits behind `MCP_SHARED_SECRET`, so the gateway has to present that bearer on the
  forwarded request. I have not verified how the pass-through supplies it, nor what it does with the
  caller's own `Authorization` header on the way through.

I have written the flow against `${GATEWAY_URL}` because that is the intended shape, and because
pointing it straight at `workflow-mcp` would mean putting the substrate's shared secret into a cloud
flow and bypassing the token validation, metering and tracing that make the call governed. I have not
changed the gateway configuration; that is someone else's change, in flight.

**The approvals decide route.** I was told it might not exist yet. It does exist in this tree, at
`POST /api/approvals/{approval_id}/decide`, accepting `decision`, `actor`, `channel`, `comment` and
`answer` and recording the channel as `api:<channel>`, which matches the contract I was given. It is
uncommitted work at the time of writing, so treat the exact field names as settled but the route as
new.

**Connector details I took from documentation, not from a tenant.** The OneDrive trigger operation ids
and the 50 MB limit on the content variant are documented. The Teams action's operation id
(`PostCardAndWaitForResponse`) and its `poster` / `location` / `body/...` parameters are documented,
but its **output schema is documented only as "dynamic"** — the `responder.email`,
`responder.userPrincipalName`, `data.<inputId>` and `submitActionId` paths the flow reads are the
widely used and widely documented-by-practitioners shape, not a published schema. Check them in a real
run before trusting the `actor` value, since that is the field that must never be wrong. The trigger's
`splitOn` path is likewise something to confirm in the designer.

**Not verified at all:** whether the assembled card fits inside Teams' message size limit for a
realistic meeting; how Teams renders mixed Arabic and English inside these text blocks (the card sets
`wrap` but does not set right-to-left, which is an Adaptive Cards 1.5 feature and may not be available
on every Teams surface); and whether an `owner` value that is a directory object id rather than a user
principal name is accepted by the process — the field's own description allows both, but I have not
run it.

**Deliberately unspecified, and left unspecified here rather than guessed:** what the `summary` object
contains beyond the recording name the card uses; what `review_app` points at; and what happens to a
run whose approval is declined. If you need those, read the process contract in
`src/lab/platform/contracts.py` or call `GET ${GATEWAY_URL}/api/processes`, which returns every
process with its inputs, their descriptions and its declared outputs — it is meant to be read by
whoever is building a flow.


# The second flow: telling the meeting its outputs exist

`notify.template.json`. Two actions, no polling, and nothing to configure but a connection.

## Why a flow at all, rather than the lab posting

Microsoft Graph will not create a chat message with application permissions — that path exists for
migration and nothing else — and this lab authenticates as an application by design (the
provider-identity rule: the caller's credential authorises the call to the MCP, the server's own
registration authorises the call to the provider). On-behalf-of is blocked on identity propagation
gateway → MCP. So no amount of consent lets the lab post as itself; the only things that can are a
registered bot or something already holding a person's Teams connection, and a Power Automate
connection is exactly the second. Uploading the files is the opposite: `Files.ReadWrite.All` is
enough, so the lab does that part itself and this flow only announces it.

The alternative shape — this flow polling `<process>_status` until the minutes finish — was rejected.
A flow sitting in a Do-until for the length of an unknown run is a worse thing to operate than a push,
and the lab already pushes outward to a Workflows webhook for approvals.

## What the lab sends

`lab.substrate.meeting_notifier` POSTs one JSON body per finished run, and only when there is
something to say: the process was `transcript_to_minutes`, it finished `done`, it resolved a
`chat_id`, and it actually delivered files. An ad-hoc "Meet now" recording resolves no meeting, so
nothing is sent — silence is the common case, not the failure case.

```json
{"chat_id": "19:meeting_...@thread.v2", "request_id": "wfr-...",
 "files": [{"name": "sync.transcript.md", "url": "https://...", "handle": "collab://item/..."}],
 "decisions": 3, "actions": 2, "speakers": 4}
```

**No meeting title.** The lab does not have one: a minutes run is a continuation started from a
transcript reference, and the title is free text a person typed, which the input contract keeps out
by design. The message posts into the meeting's own conversation, where the title is already on
screen, so it says "the minutes for this meeting" rather than carrying an empty field.

Counts, names, ids and links — never the minutes text, the transcript, or who said what. The outputs
live in the tenant behind the recording folder's own permissions, and this says **where** they are,
not **what** they say. A person who cannot open the folder gets a link that does not work, which is
the correct outcome.

`url` is the address a person opens. The `handle` beside it addresses bytes for a tool and is in the
payload only so a later flow could act on the file; it is deliberately not put in front of anyone.

## Setting it up

1. In Teams, **Workflows → Create → From blank**, trigger *"When a Teams webhook request is
   received"* — the same trigger the approval channel uses. Set *Who can trigger the flow* to **Anyone**
   (the lab sends no credential; the URL is the secret, exactly as for `TEAMS_WEBHOOK_URL`).
2. Paste the schema from `notify.template.json` into the trigger's **Request Body JSON Schema**.
3. Add **Select** (`Build_links`) and **Post message in a chat or channel** as in the template.
4. Save, copy the generated URL, and put it in `.env` as `MEETING_WEBHOOK_URL`. Then
   `deploy/railway.py substrate up` so `meeting-notifier` picks it up. **Unset, the notifier still
   runs and logs what it would have posted** — which is the right way to watch it before wiring the
   destination.

## `poster: User` or `poster: Flow bot`

The template uses **User**: the message appears as the owner of this flow's Teams connection, who
must be a member of the meeting chat. That is the honest option when the flow owner is the person who
ran the meeting, and it is the one to start with.

**Flow bot** posts as a bot instead, which avoids attributing a machine's message to a person, but the
bot has to be able to reach the chat. Meeting chats are the surface where this is least predictable,
so verify it in a real meeting before choosing it — a message that silently does not arrive is worse
than one from the wrong sender.

## What is not verified here

The `chat_id` the lab sends is `chatInfo.threadId` as Graph reports it, which is documented as the
meeting chat's thread id and is the id the Teams connector wants for a group chat. **That pairing has
not been run end to end against a scheduled meeting** — every recording tested so far was ad-hoc and
resolved no meeting at all. Nor has whether a meeting chat accepts a post from a connection that
joined the meeting but did not organise it.
