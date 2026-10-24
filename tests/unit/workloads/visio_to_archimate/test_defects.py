"""Three defects found reading visio_to_archimate end to end (24 Oct 2026).

1. The Architect's corrective retry was BLIND: the client is stateless (`store=False`), so a bare text
   correction runs in a fresh conversation that never saw the BA description — the same defect commit
   eea5830 fixed for the BA. The retry must carry the original prompt.
2. A document passed as `diagram` passed validation (only the ref's SHAPE was checked) and then fell into
   the .vsdx branch at run time. It is now refused by name at the door.
3. A local-path image was sent RAW, skipping the sizing contract every ref read gets from storage_get.
"""
import io
import json
import os
import tempfile

import pytest

from lab.platform.contracts import VISIO_TO_ARCHIMATE

from fixtures.workflow import (BA_NORMALISED, BA_OK, SPEC_OK, Agents, data_contents, harness, raises,
                               run)


# ------------------------------------------------------------------ 1. the Architect retry carries the BA
def test_the_json_mode_architect_retry_carries_the_ba_description():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": ["prose, not a spec", SPEC_OK, "done"]})
    with harness(agents) as h:
        out = run(h, "diagrams/x.vsdx")
    first, retry = h.agents.runs_of("architect-agent")[:2]
    assert json.dumps(BA_NORMALISED) in retry, "the retry must re-send what the Architect was designing from"
    assert "not a valid engine spec" in retry and first in retry
    assert out["summary"]["elements"] == 3


def test_the_tools_mode_architect_retry_carries_the_ba_description():
    def build(tools, msg):                 # the second turn builds the model through the accumulator
        tools["set_model"]("Clinic Portal")
        tools["add_elements"](SPEC_OK["elements"])
        tools["finish"]()
        return "done"

    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": ["I forgot to build anything", build, "done"]})
    with harness(agents, env={"ARCHITECT_MODE": "tools"}) as h:
        out = run(h, "diagrams/x.vsdx")
    retry = h.agents.runs_of("architect-agent")[1]
    assert json.dumps(BA_NORMALISED) in retry and "finish()" in retry
    assert out["summary"]["elements"] == 3


# ------------------------------------------------------------------ 2. a document is not a diagram
@pytest.mark.parametrize("ref", ["art://d1/brief.docx", "art://d1/brief.pdf", "art://d1/notes.md",
                                 "art://d1/model.archimate.xml"])
def test_a_document_passed_as_the_diagram_is_refused_by_name(ref):
    with pytest.raises(ValueError) as e:
        VISIO_TO_ARCHIMATE.validate({"diagram": ref})
    msg = str(e.value)
    assert "diagram" in msg and ref.rsplit("/", 1)[-1] in msg and "vsdx" in msg and "image" in msg


@pytest.mark.parametrize("ref", ["art://d1/clinic.vsdx", "art://d1/clinic.vsdx#Page-2", "art://d1/map.png",
                                 "art://d1/map.JPG"])
def test_a_diagram_or_an_image_is_still_accepted(ref):
    assert VISIO_TO_ARCHIMATE.validate({"diagram": ref})["diagram"] == ref


# ------------------------------------------------------------------ 3. local images get the sizing contract
def _png(w, h) -> bytes:
    from PIL import Image
    import random
    rnd = random.Random(7)
    im = Image.new("RGB", (w, h))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(w * h)])
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_a_local_image_is_normalised_like_a_ref_read():
    from PIL import Image
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with tempfile.TemporaryDirectory() as d, harness(agents) as h:
        png = os.path.join(d, "huge.png")
        open(png, "wb").write(_png(2000, 300))
        run(h, {"diagram": png})
    (sent,) = data_contents(h.agents.runs_of("ba-agent")[0])
    import base64
    data = base64.b64decode(sent.uri.split(",", 1)[1])
    assert max(Image.open(io.BytesIO(data)).size) <= 1600, "the 1600 px sizing contract applies to paths too"


def test_a_local_image_below_the_sizing_floor_fails_loud_like_a_ref():
    agents = Agents(**{"ba-agent": [BA_OK]})
    with tempfile.TemporaryDirectory() as d, harness(agents) as h:
        png = os.path.join(d, "dot.png")
        open(png, "wb").write(b"\x89PNG tiny")
        raises(h, {"diagram": png}, RuntimeError, "no usable image")
    assert h.agents.runs == []
