# Phase 3 — the surface people actually use

*11 Oct 2026. Decisions taken this morning are recorded with the evidence that forced them.*

Phase 2 made the fabric correct. Phase 3 makes it **reachable**: a researcher who never opens a
repository, an author who is told their document needs them, a steward who triages a queue in twenty
minutes. Everything below exists to move work to where people already are.

## The decisions, and what forced them

**ONE Teams app, not two.** The first idea was one app per cohort. Cohort was never an app boundary: a
Teams app declares SCOPES — `personal`, `team`, `groupChat` — and one manifest carries them all. Two
apps would have been two manifests, two bot registrations and two publish cycles to express something
that is really *where it is installed* and *who is looking*.

**The Copilot Studio agent IS the bot.** No bot code. It can receive a card submit through an
[Ask with Adaptive Card](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-ask-with-adaptive-card)
node (schema 1.6 and earlier; the fabric's cards are 1.4), and it already holds
`approvals_list · approvals_get · approvals_decide` — verified live 10 Oct. This also honours the lab's
own delivery-mode rule: **low code for end-user surfaces, pro code for anything touching a system of
record.** A conversational surface is the former.

**Every ASK is a DM; every CHANNEL is the record.** Not a preference — a constraint:
[proactive messages can only go to a personal chat with the agent](https://learn.microsoft.com/en-us/microsoft-copilot-studio/advanced-proactive-message).
The agent cannot post into a channel as itself. That turns out to be the right shape anyway, and it is
the same distinction the candidate threshold draws: **interruption versus visibility.** An owner card
names ONE person, so a channel broadcasting it was always slightly wrong; a steward's queue is shared
and periodic, so a channel showing what is open is right.

**Therefore stewards are NAMED.** A proactive DM goes to a person. A channel makes stewardship "whoever
is in the room"; a DM makes it a role somebody holds — which is what the BRS already says ("curated by a
named steward per scheme") and what CLAUDE.md calls "a new role with a small, measured workload".

**Role-aware surfaces are a COURTESY, never a control.** A researcher sees no approval verbs because
they are irrelevant, never because that is how they are prevented. Authority stays where it is: the
gateway's per-tool grants (`ApprovalTools.READ` vs `.WRITE`) and `ApiRoles.Approvals.Decide`. A hidden
button is security by absence, and this lab's whole argument is that the control plane is real.

**Independent of the meeting app at runtime** (user, 11 Oct; the same rule given for the steward channel
on 10 Oct and verified then by reading imports). Its own app registration, its own substrate service,
its own manifest. Shared MODULES, never a shared process — the lab's normal shape.

## What it looks like

```
ONE Teams app  "Fabric"
  staticTab        personal   the visualisation + what is mine
  configurableTab  team       the visualisation, in a channel
  bot              personal   the Copilot Studio agent — ask, retrieve, impact, decide

ASK       a DM from the agent        "this one is yours, now"
RECORD    pilot-approvals            what is open, who decided
          pilot-vocabulary           the steward queue, visible to the team
```

## Tasks

### T3.0 — The app shell
Manifest (`config/clients/fabric-app/`), a substrate service serving the tab, its own app registration.
Model on `lab.substrate.meetingapp` and reuse its hard-won lessons, none of which are rediscoverable
cheaply: **publish via Graph, not a Teams upload**; the tab's **configuration page is mandatory** or the
add silently cancels (measured 6 Oct); `validDomains` is the service's own public host. Serve with **no
`X-Frame-Options`**, which is how the meeting app's pages already frame inside Teams.

### T3.1 — Custody lookup by URL (FR-4.1.4)
Retrieval hands the assistant a SharePoint URL; the catalogue is keyed by `collab://item/<drive>/<item>`.
`semantic_catalog_by_url(url)` resolves one to the other, or returns nothing. Without it the overlay
falls back to title matching, which is silently wrong on duplicates — the exact failure FR-3.3 exists to
surface. **Do this before T3.2**: the agent's governed answers depend on it.

### T3.2 — The agent: knowledge source and instructions
A Knowledge-tab change (pilot library + site), then instructions: governed questions — *who owns this, is
it approved, what does it affect, how do we know, is this a duplicate* — **always** call the fabric and
never answer from knowledge sources; retrieval questions use knowledge sources; and the agent **says when
it did not consult the fabric**. No routing code: tool selection is the routing.

### T3.3 — The tab: the visualisation, live
`semantic_view_corpus` already draws the whole catalogue in one governed call (4.9 s at 61 records). In a
tab it gains three things it cannot have as a file in SharePoint: **external scripts are allowed** (the
vendored D3 stays, but the constraint is gone), it can be **live rather than a snapshot**, and **TeamsJS
knows who is looking** — so a steward lands on `Vocabulary` with the candidate register beside it and a
researcher lands on `About` with the filters. Same `TopologyView`, same `viz_d3`, different default:
exactly what the renderer port was built for.

### T3.4 — Asks by DM, answered on the card
Replaces yesterday's `PostCardAndWaitForResponse` flow for ASKING. The new flow is one action —
*"Post message in a chat"*, **Post as: Microsoft Copilot Studio agent** — with no wait and no dynamic
schema, so neither trap from 10 Oct applies. The agent's topic then asks with the Adaptive Card and calls
`approvals_decide` with the signed-in person as `actor`.

```
lab -> webhook -> flow: post as the agent, to a NAMED steward or the record's OWNER
     -> agent topic: Ask with Adaptive Card
     -> the person answers in the DM
     -> agent calls approvals_decide
```

Carry a unique id in every submit so the agent knows which card an answer came from — Microsoft calls
this out, and the fabric's cards already do it (`request_id` rides the Submit `data`, added 10 Oct for a
different reason).

Constraint to respect: the flow must live in the **same Power Platform environment** as the agent. Ours
both do (`socratespersonal (default)`).

### T3.5 — Linked projection pages
`fabric_projector.page()` renders subjects and references as plain text, so a reader hits a dead end.
Emit Markdown links, decide what a concept page is, and then — as an INSTRUMENT, not a candidate — point
Obsidian at a synced copy to answer the only question a wiki stack is for: *does anybody actually wander
this?* Standard `[label](slug.md)` links, never `[[wikilinks]]`: the test tool must not dictate a
non-portable syntax.

## What this DELETES

- the `PostCardAndWaitForResponse` flow and its designer-only action
- `TEAMS_STEWARD_ANSWERS_ON_CARD` — a bot can always receive, so the flag has nothing to guard
- any need for custom bot code

## What needs a PERSON, and when

The default is that I do it by API. Everything below was checked on 11 Oct rather than assumed, because
"a human has to" was wrong twice yesterday — the Teams channel and the whole Power Automate flow both
turned out to be reachable with the user's DELEGATED `az` session, which is a different credential from
the lab's application one.

| | route | proven |
|---|---|---|
| Copilot Studio **topics** | Dataverse Web API, `botcomponent` (`ComponentType` 0 / 9) | the org answers the `az` token; its 8 agents list, incl. `Documentation Fabric` |
| Teams **app registration** | Microsoft Graph | the pattern `entra_provision.py` already uses |
| Teams **app publish + install** | Graph `appCatalogs/teamsApps` | the meeting app's own lesson: publish via Graph, NOT a Teams upload |
| **Flows** | Flow API | created three yesterday |
| **Teams, channels** | Graph (delegated) | created the Fabric team and six channels yesterday |

**Likely to need you, and front-loaded so it does not interrupt:**

1. **Publishing the agent** after its topics change. Copilot Studio has a publish step; whether it is an
   API action or a button is the one thing still to establish. If it is a button it is one click, and I
   will say so before starting rather than halfway through.
2. **Tenant approval of the Teams app**, if this tenant requires admin consent for a custom app. You are
   the admin, so this is a click rather than a blocker — but it is a click.
3. Nothing else is expected. The moment I hit something that is genuinely yours, I stop and say so with
   the exact steps, as with the one Power Automate action yesterday.

## Answers taken, 11 Oct

**Stewards, authors and researchers are all the same person today** — the user wears all three hats for
the pilot, so a steward list is a setting with one name in it and the cohort differences are exercised
by behaviour rather than by membership. That is enough to prove the shapes; naming real stewards is a
pilot decision, not an engineering one.

**An owner DOES get a DM**, with the channel as the fallback. An ask that cannot be delivered — no app
installed, no chat — must land in `pilot-approvals` rather than vanish. Silence is the one outcome this
gate may never produce.

**The tab reads with the SERVICE'S credential and says so on the page.** Identity propagation
gateway→MCP is still blocked, so the alternative is not available; and a corpus picture carries counts,
labels and links and no document content, so it is honest for every member of the team to see the same
one. Saying so is the part that makes it honest rather than convenient.

## Open questions

1. **Can a topic's Ask-with-Adaptive-Card node be authored as data?** Topics live in `botcomponent.data`;
   whether that round-trips cleanly for this node type is the first thing T3.2 establishes, and the
   answer decides whether the agent is configured by API or by hand.
2. **Is publishing the agent an API action?** See above — front-loaded deliberately.
3. **What happens to the 43 open concept-admission cards** when asks move to DM? They are the record;
   the asks that follow are new. Worth deciding whether the backlog is re-asked or left as history.

## Sequence

T3.0 → T3.1 → T3.2 → T3.3 → T3.4 → T3.5. The app shell first because everything else installs into it;
custody before the agent because its answers depend on it; the DM path last among the mechanics because
it is the only one that needs the agent to already work.


## Carried forward — the first item of the next phase

**The fabric can ingest its own output, and T3.5 made that more likely.** A page written into the wiki
folder is tagged `fabric-written` so the ingress drops the change event it causes — but that tag has a
**7-day TTL**, and nothing excludes `FABRIC_WIKI_FOLDER` from the sweep BY NAME. A projection not
rewritten inside seven days becomes an ordinary document to the sweep: catalogued, classified, and given
a review card for a page the fabric wrote itself.

It already applied to record pages and the measurements page. T3.5 adds **one file per concept**, each
rewritten only when a record about THAT concept publishes — so a quiet concept's page is exactly the
file most likely to go past the window. The exposure did not change in kind; it changed in how many
files sit in the risky state and for how long.

The proportionate fix is a **folder-level exclusion** — the sweep skips the wiki folder because it is
the fabric's own, not because a marker happens to be fresh. A TTL is a race; a rule is a rule. Deferred
deliberately (user, 11 Oct 2026) rather than taken mid-phase, and first in the next one.
