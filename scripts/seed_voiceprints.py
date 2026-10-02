"""Seed the voiceprint gallery from VERIFIED speech — the operator's one-off, through the production path.

Why not write the rows directly: the gallery lives in the substrate's own database, reachable only from
inside the deployment. So this goes through the same governed tool the pipeline uses — `speech_enrol` on
speech-mcp, via the gateway — and seeding therefore also proves that path end to end.

What it needs, and why each piece:
  * a SEED FILE of verified segments per recording — `{"<rec>": [{"speaker": "P1", "start": s, "end": e}]}`
    — times and pseudonyms only, never a word. Verified means a person confirmed who spoke each span
    (the 29 Sep POC: voiceprint groups named by the organiser), because a diarizer label MIXES people and
    seeding from one would give a person another's voice.
  * the RECORDINGS as `art://` refs already in the upload store (a meeting run's `recording_ref`).
  * WHO each pseudonym is — `{"P1": {"identity": "..."}, "P2": {"tag": "..."}}` — and who attests that
    each of them CONSENTED. Consent was obtained outside the lab; this script records who vouches for it.

Usage:
  set -a && source .env && set +a
  .venv/bin/python scripts/seed_voiceprints.py --seed var/voiceprint/seed.json \\
      --recording m29=art://…/Meeting Recording.mp4 --recording m28=art://…/Meeting Recording.mp4 \\
      --people '{"P1": {"identity": "me@x"}, "P2": {"tag": "Nabeel"}, "P3": {"tag": "Ahmed"}}' \\
      --consented-by me@x [--dry-run]

The seed file's timeline is uploaded as a segments artifact (times and pseudonyms only). Names travel in
ONE argument, `speaker_map`, to `speech_enrol` — the same argument the pipeline sends after an approval.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from lab.platform.contracts import SemanticTools, SpeechTools


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--seed", required=True)
    p.add_argument("--recording", action="append", required=True, help="KEY=art://ref, one per recording")
    p.add_argument("--people", required=True, help="JSON: pseudonym -> {identity|tag}")
    p.add_argument("--consented-by", required=True)
    p.add_argument("--source", default="seed: verified segments, consent attested by the organiser")
    p.add_argument("--gateway", default=os.environ.get("PUBLIC_GATEWAY_URL", ""))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def plan(seed: dict, recordings: dict, people: dict) -> list[dict]:
    """One enrol call per recording: its segments (only the people being seeded) and the answer."""
    out = []
    for key, ref in recordings.items():
        segs = [dict(s, text="(verified speech)", language="") for s in seed.get(key, []) if s["speaker"] in people]
        if not segs:
            continue
        here = {s["speaker"] for s in segs}
        out.append({"recording": key, "audio_ref": ref, "segments": segs,
                    "speaker_map": {p: dict(people[p], consent="yes") for p in sorted(here)}})
    return out


async def run(args) -> None:
    seed, people = json.load(open(args.seed)), json.loads(args.people)
    recordings = dict(r.split("=", 1) for r in args.recording)
    calls = plan(seed, recordings, people)
    for c in calls:
        secs = {p: round(sum(s["end"] - s["start"] for s in c["segments"] if s["speaker"] == p))
                for p in c["speaker_map"]}
        print(f"{c['recording']}: {len(c['segments'])} verified segments, seconds per person {secs}")
    if args.dry_run:
        return
    url = args.gateway.rstrip("/") + "/mcp/"
    headers = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    async with Client(StreamableHttpTransport(url, headers=headers)) as client:
        names = {t.name.split("-", 1)[-1]: t.name for t in await client.list_tools()}
        for c in calls:
            t0 = time.monotonic()
            stored = (await client.call_tool(names[SemanticTools.store_spec], {
                "spec": {"segments": c["segments"]}, "name": f"voiceprint-seed-{c['recording']}.segments.json"},
                timeout=120)).data
            got = (await client.call_tool(names[SpeechTools.enrol], {
                "audio_ref": c["audio_ref"], "segments_ref": stored["spec_ref"], "speaker_map": c["speaker_map"],
                "consented_by": args.consented_by, "source": args.source},
                timeout=290)).data              # under the gateway's 300 s: a hang must end, not wait forever
            print(f"{c['recording']}: {time.monotonic() - t0:.0f}s — enrolled {got.get('enrolled')} skipped {got.get('skipped')} (model {got.get('model')})")


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
