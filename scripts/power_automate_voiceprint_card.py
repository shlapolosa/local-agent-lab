"""Apply the voiceprint card changes to the speaker-mapping flow — ONE implementation, so the committed
template and the live flow cannot be edited two different ways.

The card gains: a "Recognised as X (voice match 0.52)" line when a voiceprint matched, the identity or
tag box PRE-FILLED from that suggestion, and a CONSENT toggle per speaker (default off) whose "yes" is
the only thing that lets a voice be kept. The answer then carries `"consent": "yes"` for ticked
speakers and nothing at all for the rest.

  .venv/bin/python scripts/power_automate_voiceprint_card.py config/clients/power-automate/flow.template.json
  .venv/bin/python scripts/power_automate_voiceprint_card.py --live <environment> <flow-id> [--dry-run]

Idempotent: applying it twice changes nothing the second time. `--live` reads the flow with the operator's
`az` login, applies the same edit, and PATCHes it back with its connection references intact.
"""
import json

SUG = "item()?['suggestion']"
SUGGESTION_LINE = {
    "type": "TextBlock", "wrap": True, "color": "Accent", "spacing": "Small",
    "text": (f"@{{if(empty(coalesce({SUG}, json('{{}}'))), '', concat('Recognised as ', "
             f"coalesce({SUG}?['display'], ''), ' (voice match ', string(coalesce({SUG}?['score'], 0)), "
             f"') — check it, and change it if it is wrong'))}}"),
    "isVisible": f"@not(empty(coalesce({SUG}, json('{{}}'))))",
}
CONSENT = {
    "type": "Input.Toggle", "id": "@{concat('consent_', item()['label'])}",
    "title": "Consent — they agreed to have their voice remembered",
    "valueOn": "yes", "valueOff": "no", "value": "no",
}


def find(o, name):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == name:
                return v
            r = find(v, name)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find(v, name)
            if r is not None:
                return r


def apply(defn: dict) -> dict:
    blocks = find(defn, "Build_speaker_blocks")["inputs"]["select"]["items"]
    ids = {b.get("id", ""): b for b in blocks}
    if not any(b.get("type") == "Input.Toggle" for b in blocks):
        at = next(i for i, b in enumerate(blocks) if b.get("type") == "Input.ChoiceSet")
        blocks.insert(at, SUGGESTION_LINE)
        blocks.append(CONSENT)
    for b in blocks:
        if b.get("id", "").startswith("@{concat('identity_'"):
            b["value"] = f"@{{coalesce({SUG}?['identity'], '')}}"
        if b.get("id", "").startswith("@{concat('tag_'"):
            b["value"] = f"@{{coalesce({SUG}?['tag'], '')}}"
    read = find(defn, "Read_the_answers")["inputs"]["select"]
    read["consent"] = ("@coalesce(body('Ask_the_organiser')?['data']?[concat('consent_', item()['label'])], 'no')")
    add = find(defn, "Add_one_speaker")["inputs"]
    base = ("if(empty(item()['identity']), setProperty(json('{}'), 'tag', item()['tag']), "
            "setProperty(json('{}'), 'identity', item()['identity']))")
    add["value"] = (f"@setProperty(variables('answer'), item()['label'], if(equals(item()?['consent'], 'yes'), "
                    f"setProperty({base}, 'consent', 'yes'), {base}))")
    return defn


def live(environment: str, flow_id: str, dry_run: bool = False) -> None:
    import subprocess
    import urllib.request
    tok = subprocess.run(["az", "account", "get-access-token", "--resource", "https://service.flow.microsoft.com/",
                          "--query", "accessToken", "-o", "tsv"], capture_output=True, text=True, check=True).stdout.strip()
    url = (f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{environment}"
           f"/flows/{flow_id}?api-version=2016-11-01")
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    flow = json.load(urllib.request.urlopen(urllib.request.Request(url + "&$expand=properties.definition", headers=hdr)))
    props = flow["properties"]
    before = json.dumps(props["definition"], sort_keys=True)
    apply(props["definition"])
    if json.dumps(props["definition"], sort_keys=True) == before:
        print(f"{props.get('displayName')}: already has the voiceprint card — nothing to change")
        return
    if dry_run:
        print(f"{props.get('displayName')}: would update the card (dry run)")
        return
    body = {"properties": {"definition": props["definition"],
                           "connectionReferences": props.get("connectionReferences") or {},
                           "displayName": props.get("displayName")}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr, method="PATCH")
    with urllib.request.urlopen(req) as r:
        print(f"{props.get('displayName')}: card updated (HTTP {r.status})")


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "--live":
        live(sys.argv[2], sys.argv[3], dry_run="--dry-run" in sys.argv)
    else:
        path = sys.argv[1]
        d = json.load(open(path))
        json.dump(apply(d), open(path, "w"), ensure_ascii=False, indent=2)
        print("applied to", path)
