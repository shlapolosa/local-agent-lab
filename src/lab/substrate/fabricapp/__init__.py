"""The Documentation Fabric's Teams app: ONE app, a tab that draws the corpus, and the Copilot Studio
agent as its bot.

ONE app and not one per cohort (user decision, 11 Oct 2026). A Teams app declares SCOPES — `personal`,
`team`, `groupChat` — and one manifest carries them all, so "steward" and "researcher" are *where it is
installed* and *who is looking*, never two manifests, two bot registrations and two publish cycles.

NO BOT CODE. The agent the lab already runs (`Documentation Fabric`, bot registration
d6e12678-…) is declared as this app's bot, so asking, retrieving, impact and deciding are the tools it
already holds — `approvals_list · approvals_get · approvals_decide`, verified live 10 Oct. What this
package adds is the one thing a conversation cannot be: a PICTURE.

INDEPENDENT OF THE MEETING APP at runtime (user, 11 Oct; the same rule given for the steward channel the
day before). Its own app registration, its own service, its own manifest. It may share MODULES with
`lab.substrate.meetingapp` — both serve Teams tabs — but never a process.
"""
