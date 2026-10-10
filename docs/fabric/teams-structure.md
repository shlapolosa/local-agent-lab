# Structuring Teams and channels — a proposal

*10 Oct 2026. The first step is APPLIED — the `Fabric` team exists. The rest is still a proposal.*

## The inventory, as it actually stands

| Team | Channels | What it is |
|---|---|---|
| `socratespersonal` | General · **lab-approvals** | the personal/default team, doing lab work |
| `AI Use-Case Intake PoC` | General · **ai-use-cases** · **Vocabulary stewards** | the pilot: its SharePoint library is the corpus the fabric watches |
| `Lab Production` | General · **Approvals** | the production tenant scope |
| *(two groups named `All Company`)* | — | created Apr and Sep; duplicates |
| `Laboratory-UseCases` | `use case agent` | **unidentified** — in the sidebar, but not in `joinedTeams`, `associatedTeams` or `memberOf` |

## Why it is hard to navigate

Three different axes are being used as if they were one.

1. **Environment** — dev/pilot vs production (`AI Use-Case Intake PoC` vs `Lab Production`)
2. **Workload** — meeting minutes, use-case intake, the fabric (`ai-use-cases`, `use case agent`)
3. **Audience** — owners, stewards, researchers (`lab-approvals`, `Vocabulary stewards`)

Any one of them is a reasonable way to divide things. Using all three at once, inconsistently, means a
name never tells you which axis you are on — so `AI Use-Case Intake PoC` and `Laboratory-UseCases` look
like the same thing described twice, and approvals live in three unrelated places.

## The rule to decide by

> **A team is a boundary of MEMBERSHIP AND DATA. A channel is a boundary of ATTENTION.**

- A **team** carries a SharePoint site, a document library and a membership list. Two things belong in
  different teams when **different people may read them**, or when **their documents must not mix**.
  Environment is such a boundary: production data is not pilot data.
- A **channel** carries no data boundary worth anything — it carries *whether you need to look now*. That
  is tempo and audience, which is exactly what the steward split proved on 10 Oct: 101 vocabulary cards
  against ~37 owner cards, each burying the other.

Workload is **neither**. The meeting pipeline, use-case intake and the fabric share one corpus and one set
of people. They are not a data boundary and they are not a tempo — so they should not be teams, and should
not be channels either. The approval payload already carries `process`, so a card can say which workload
raised it. **The workload belongs in the card, not in the navigation.**

## Proposed shape

Two teams, by environment. Inside each, channels by audience.

```
LAB (pilot)                            — the corpus the fabric watches
  General          team notices
  Approvals        OWNER cards, every workload — urgent, you are named
  Vocabulary       STEWARD cards — deliberate, periodic            (exists)
  Ask              where researchers talk to the Copilot agent; no cards

LAB PRODUCTION                         — production tenant scope
  General · Approvals · Vocabulary · Ask     (the same four, so the shape is learnable once)
```

The symmetry is the point: the same four channels in both teams means a person learns the structure once,
and "which environment am I in" is the only question left — which is the one that actually matters,
because it is the data boundary.

### What changes

| Today | Proposal | Why |
|---|---|---|
| `lab-approvals` in `socratespersonal` | fold into the pilot team's `Approvals` | lab work in a personal team has no membership story |
| `ai-use-cases` | fold into `Approvals` | it is an audience channel named after a workload |
| `Vocabulary stewards` | rename `Vocabulary` | the team already says whose; the channel says what |
| `AI Use-Case Intake PoC` | rename to something that is not one workload | it is the whole lab's pilot corpus now, not use-case intake |
| two `All Company` groups | retire one | duplicates |
| `Laboratory-UseCases` | identify, then fold or retire | nobody can navigate what they cannot classify |

### Renaming is cheaper than it looks

`FABRIC_ALLOWLIST` is keyed on **drive IDs** (`b!y9BJ7yalzU…`), not on team or site names. So renaming a
team does not move its library, does not change the drive id, and does not touch the fabric's allow-list,
the sweep, or any `collab://` handle already in the catalogue. The cost of a rename here is the muscle
memory of the people in it, and nothing else.

### What stays as it is

- **`Lab Production` stays a separate team.** That is a real data boundary, not a naming preference.
- **The audience split stays** — it is the one axis measured to matter.
- **No per-workload channels.** If a workload ever needs its own *working conversation* (not its cards),
  that is a channel for the conversation, named for the conversation.

## What was decided and built, 10 Oct 2026

The user's judgement, and it improved the proposal in two places.

**Workload CAN be a team, where the data and the readers genuinely differ.** The original draft said
workload was never a boundary. That was too quick: the allow-list already spans TWO drives — the pilot
library and the organiser's `Recordings` folder — so data boundaries already exist and already do not
follow team lines. The people who may read meeting recordings are not the people who may read use-case
submissions, and in an enterprise that is not optional. **Meeting is left exactly as it is** until there
is a reason to move it; the shape is worth testing on one workload before it is spent on three.

**But the fabric is not a peer of the workloads — it catalogues them.** So `Fabric` is a CROSS-CUTTING
team, not a workload team. That is what settles the question the per-workload shape could not answer:
there is ONE vocabulary serving every workload, so a `vocabulary` channel per workload would be three
doors onto the same room, and a steward would have to watch all of them to see terms that arrived from
anywhere.

**Environment is a channel here, not a team, and the reason is specific rather than a compromise.** A
team is a data boundary because it carries a document library. A fabric card carries **links, ids and
counts and never document content** — a rule with a test behind it, because spans and channel posts are
held to it. So an approvals channel is not the kind of thing a library is, and pilot/prod as channels
costs nothing real. If production ever needs true separation, a PRIVATE channel has its own membership
AND its own storage, available later without restructuring any of this.

### What exists now

```
Fabric
  pilot-approvals     an OWNER is asked about THEIR record — urgent, personal, you are named
  pilot-vocabulary    a STEWARD triages terms — deliberate, periodic, one card many terms   [wired]
  pilot-agent         ask the fabric: who owns this, is it approved, what does it affect
  prod-approvals · prod-vocabulary · prod-agent      the same three, no webhooks yet
```

Environment first in the name so the two tiers sort apart, audience second — the two questions a person
actually asks ("which corpus?" then "is this mine to answer?"), answered left to right.

`prod-*` deliberately has no webhooks: production runs a different gateway and a different `.env`, so
those are three more flows at cutover, not now.

### What it cost to move a channel

The `Vocabulary stewards` channel created an hour earlier, in the wrong team, was replaced by
`pilot-vocabulary`: a new channel, a new Power Automate flow, and **one `.env` line**. The old flow was
STOPPED and the old channel DELETED rather than left disabled — a dormant webhook is how a surprise card
arrives in six months.

One setting, because the fabric does not know which channel it posts to. That is the whole payoff of a
channel being an adapter behind a URL instead of code, and it is the reason every step below is
reversible.

## Sequence for the rest, if adopted

1. **Identify `Laboratory-UseCases`** — it is in the sidebar but appears in neither `joinedTeams`,
   `associatedTeams` nor `memberOf`, so nobody can say what it is. You cannot plan around an object
   nobody can classify, and an unclassifiable object in the navigation is a large part of why the
   navigation is hard.
2. **Point `TEAMS_WEBHOOK_URL` at `Fabric/pilot-approvals`** — the fabric's owner cards then sit beside
   its steward cards, under one team that says what it is. One `.env` line, as the steward move was.
3. **Retire `lab-approvals`** (lab work in a personal team has no membership story) once it is quiet.
4. **Leave `ai-use-cases` to the use-case workload.** It is that workload's channel, not the fabric's,
   and this proposal deliberately stops at the fabric's own boundary.
5. **Retire the duplicate `All Company`** (two groups of that name, April and September).
6. **At production cutover**, three flows for the `prod-*` channels and the production `.env`.

Each step is independently reversible and none of them touches a document.

## The open question this does NOT answer

A fabric owner-card says "is this record right — you own it". It is addressed to a PERSON, and a channel
broadcasts to a room. `pilot-approvals` is the right place for them to be *visible* and *auditable*, but
the honest form of "you own this, please confirm" is a chat or an @mention, not a post everyone scrolls
past. Worth revisiting once there are enough owners for the difference to be felt.
