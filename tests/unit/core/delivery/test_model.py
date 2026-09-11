import pytest

from lab.core.delivery import KINDS, DeliveryContext, DeliveryRepository


def test_key_and_iri():
    c = DeliveryContext("meeting", "AAMk1", label="Weekly EA", owner="a@x.org", source="lab")
    assert c.key == "meeting:AAMk1" and c.iri == "urn:fabric:context:meeting:AAMk1"
    assert DeliveryContext.parse("usecase:UC-42").key == "usecase:UC-42"


def test_kinds_are_closed_and_ids_opaque():
    assert set(KINDS) == {"usecase", "meeting", "submission", "workitem"}
    for bad in (("ticket", "1"), ("meeting", ""), ("meeting", "has space"), ("meeting", "https://x")):
        with pytest.raises(ValueError):
            DeliveryContext(*bad)
    with pytest.raises(ValueError):
        DeliveryContext.parse("no-colon")


def test_port_is_a_protocol():
    class Fake:
        def context(self, key):
            return DeliveryContext.parse(key)
    assert isinstance(Fake(), DeliveryRepository)
