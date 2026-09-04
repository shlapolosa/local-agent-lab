"""TDD (T5 flake): `pending()` ordered by a seconds-resolution display timestamp — two requests in the
same second sorted non-deterministically. Contract: pending() preserves insertion order regardless of
the display timestamp's resolution (a monotonic `created_ts` sort key), and old hashes without the
field still sort. Offline via the shared FakeRedis."""


from fixtures.fakes import FakeRedis, patched_client
from lab.substrate import approvals
from lab.platform import workflows


def test_approvals_pending_keeps_insertion_order_within_one_second():
    fake = FakeRedis()
    with patched_client(fake):
        approvals._now = lambda: "2026-09-03T10:00:00"        # frozen display clock
        ids = [approvals.request("adoit_import", f"subj-{i}", {}, "tester") for i in range(6)]
        assert [s["request_id"] for s in approvals.pending()] == ids


def test_workflows_pending_keeps_insertion_order_within_one_second():
    fake = FakeRedis()
    with patched_client(fake):
        workflows._now = lambda: "2026-09-03T10:00:00"
        ids = [workflows.request("visio_to_archimate", [f"art://{i}/x.vsdx"], []) for i in range(6)]
        assert [s["request_id"] for s in workflows.pending()] == ids


def test_pending_tolerates_hashes_without_the_sort_key():
    fake = FakeRedis()
    with patched_client(fake):
        rid = approvals.request("adoit_import", "old", {}, "tester")
        fake.hset(f"approvals:req:{rid}", "created_ts", "")  # emulate a hash written before this change
        assert approvals.pending()[0]["request_id"] == rid


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
