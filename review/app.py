"""Architecture Review — the human approval channel for EA repository writes.

Reads approval requests from Redis Streams (consumer group "review-app"), renders the
model's views + summary, and records approve / request changes / decline. The decision
flows back on approvals:decisions where the requesting workflow/tool picks it up. Telegram
is the other channel on the same streams (channels/telegram.py).

Run: ./lab.sh review   (streamlit, http://127.0.0.1:8501)
"""
import base64
import os
import sys
import xml.etree.ElementTree as ET

import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared import approvals, artifacts, config  # noqa: E402

JAEGER = config.JAEGER_UI_URL.rstrip("/") + "/trace/"
NS = {"a": "http://www.opengroup.org/xsd/archimate/3.0/"}

st.set_page_config(page_title="Architecture Review", page_icon="🏛️", layout="wide")

if config.REVIEW_APP_PASSWORD:      # minimal gate; production fronts this app with Entra / an identity-aware proxy
    if st.session_state.get("authed") is not True:
        pw = st.text_input("Review app password", type="password")
        if pw == config.REVIEW_APP_PASSWORD:
            st.session_state["authed"] = True; st.rerun()
        st.stop()

# drain this channel's unseen events (mark delivered) — the pending set drives the UI
for eid, _ in approvals.channel_events("review-app", block_ms=0):
    approvals.ack("review-app", eid)

st.title("Architecture Review")
reviewer = st.sidebar.text_input("Reviewer", value=os.environ.get("USER", "reviewer"))
items = approvals.pending()
st.sidebar.metric("Pending", len(items))
if not items:
    st.info("No models awaiting review. Runs that call `adoit_request_import` will appear here.")
    st.subheader("Recent decisions")
    for h in approvals.history(20):
        st.write(f'`{h["request_id"]}` **{h["decision"]}** by {h["actor"]} via {h["channel"]} — {h["comment"]} ({h["decided_at"]})')
    st.stop()

choice = st.sidebar.radio("Requests", [f'{i["subject"]} · {i["request_id"]}' for i in items])
req = items[[f'{i["subject"]} · {i["request_id"]}' for i in items].index(choice)]
p = req["payload"]

st.subheader(req["subject"])
c1, c2, c3, c4 = st.columns(4)
c1.write(f'**Request** `{req["request_id"]}`'); c2.write(f'**From** {req["requester"]}')
c3.write(f'**Status** {req["status"]}'); c4.write(f'**Created** {req["created_at"]}')
if req.get("trace_id"):
    st.write(f'**Trace** [{req["trace_id"][:16]}…]({JAEGER}{req["trace_id"]}) — the run that produced this model')
if req.get("comment"):
    st.warning(f'Last comment ({req.get("decided_by")} via {req.get("decided_via")}): {req["comment"]}')

summ = p.get("summary", {})
m = st.columns(5)
for col, k in zip(m, ("elements", "relations", "views", "violations", "warnings")):
    col.metric(k, summ.get(k, "—"))

# --- model contents (from the artifact store; legacy requests carried local paths) ---
def _xml_bytes():
    if p.get("xml_ref"):
        return artifacts.store().get(p["xml_ref"]), p["xml_ref"].split("/")[-1]
    if p.get("xml_path") and os.path.exists(p["xml_path"]):
        return open(p["xml_path"], "rb").read(), os.path.basename(p["xml_path"])
    return None, None
xml_bytes, xml_name = _xml_bytes()
if xml_bytes:
    root = ET.fromstring(xml_bytes)
    els = root.findall(".//a:elements/a:element", NS)
    rels = root.findall(".//a:relationships/a:relationship", NS)
    with st.expander(f"Model contents — {len(els)} elements, {len(rels)} relationships"):
        by_type = {}
        for e in els:
            by_type.setdefault(e.get("{http://www.w3.org/2001/XMLSchema-instance}type"), []).append(
                e.find("a:name", NS).text)
        for t in sorted(by_type):
            st.write(f"**{t}**: " + ", ".join(sorted(by_type[t])))
    st.download_button("Download .archimate.xml", xml_bytes, file_name=xml_name, mime="application/xml")
else:
    st.error(f"model artifact not available: {p.get('xml_ref') or p.get('xml_path')}")

# --- views ---
views = []                                   # [(label, bytes)]
for label, ref in (p.get("svg_refs") or {}).items():
    try:
        views.append((label, artifacts.store().get(ref)))
    except Exception as e:                   # noqa: BLE001
        st.warning(f"view {label}: {e}")
for spath in p.get("svgs", []):              # legacy: local paths
    if os.path.exists(spath):
        views.append((os.path.basename(spath).split("-", 1)[-1][:-4], open(spath, "rb").read()))
if views:
    tabs = st.tabs([v[0] for v in views])
    for tab, (_, svg_bytes) in zip(tabs, views):
        with tab:
            data = base64.b64encode(svg_bytes).decode()
            st.markdown(f'<div style="overflow:auto;max-height:75vh;border:1px solid #ccc">'
                        f'<img src="data:image/svg+xml;base64,{data}"/></div>', unsafe_allow_html=True)

# --- decision ---
st.divider()
comment = st.text_area("Comment (required for changes / decline)")
b1, b2, b3 = st.columns(3)
def _decide(d):
    if d != "approve" and not comment.strip():
        st.error("A comment is required for that decision."); return
    approvals.decide(req["request_id"], d, reviewer, "review-app", comment.strip())
    st.success(f"Recorded: {d}"); st.rerun()
if b1.button("✅ Approve — release for import", type="primary"): _decide("approve")
if b2.button("✏️ Request changes"): _decide("update")
if b3.button("⛔ Decline"): _decide("decline")
