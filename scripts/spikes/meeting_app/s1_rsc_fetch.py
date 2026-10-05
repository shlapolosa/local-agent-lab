"""SPIKE S1: can the app read a meeting's recording and transcript by RSC alone (no access policy)?

Usage: s1_rsc_fetch.py <organiser-aad-id> <msGraphResourceId>   (both are in var/spike/meeting_app.jsonl)"""
import sys

from rsc import graph

org, mid = sys.argv[1], sys.argv[2]
base = f"/users/{org}/onlineMeetings/{mid}"
print("meeting   ", *graph("GET", base + "?$select=subject,chatInfo,participants"))
status, recs = graph("GET", base + "/recordings")
print("recordings", status, recs if status != 200 else [r["id"][:16] + "…" for r in recs["value"]])
if status == 200 and recs["value"]:
    print("content   ", *graph("GET", f"{base}/recordings/{recs['value'][-1]['id']}/content", raw=True, limit=1 << 20)[:2])
status, trs = graph("GET", base + "/transcripts")
print("transcripts", status, trs if status != 200 else len(trs["value"]))
if status == 200 and trs["value"]:
    s, ctype, body = graph("GET", f"{base}/transcripts/{trs['value'][-1]['id']}/content?$format=text/vtt", raw=True)
    print("vtt       ", s, ctype, len(body), "bytes")
