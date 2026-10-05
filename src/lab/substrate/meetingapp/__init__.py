"""The opt-in Teams meeting app: a meeting opts in by adding it, and its organiser answers the
speaker question in the meeting chat (docs plan "the meeting pipeline as an opt-in Teams meeting app").

A SUBSTRATE service, like the review app: it records a person's decision through `approvals` and
starts runs through `workflows`, in-process over Redis — the front door's REST surface is for callers
outside the substrate. Its own identity is the bot, the resource-specific-consent principal, and
nothing else: it holds no Graph data permission, which stays behind graph-mcp."""
