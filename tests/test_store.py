import pytest

from hibor_cli.models import ReportMeta
from hibor_cli.store import Store


def meta(n: int) -> ReportMeta:
    return ReportMeta(id=f"id{n:04d}xxxx", url=f"https://x/{n}", title=f"报告{n}", published="2026-09-18",
                      org="o", column="", authors="", rating="", pages="")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state" / "db.sqlite")
    yield s
    s.close()


def handled(store, rid, folder):
    return store.is_done(rid, folder)


class TestDedupe:
    def test_unknown_is_not_done(self, store):
        assert handled(store, "nope", "个股_紫金") is False

    @pytest.mark.parametrize("status", ["done", "empty", "filtered"])
    def test_finished_statuses_are_never_retried(self, store, status):
        # empty/filtered cost a detail request too; re-running must not pay for them again
        store.mark(meta(1), "个股_紫金", status)
        assert handled(store, "id0001xxxx", "个股_紫金") is True

    def test_failures_are_retried_by_the_next_run(self, store):
        store.mark(meta(1), "个股_紫金", "failed", error="TimeoutError")
        assert handled(store, "id0001xxxx", "个股_紫金") is False

    def test_the_same_report_can_be_done_for_one_folder_and_new_for_another(self, store):
        store.mark(meta(1), "个股_紫金", "done", path="a.md")
        assert handled(store, "id0001xxxx", "个股_紫金") is True
        assert handled(store, "id0001xxxx", "行业_有色金属") is False

    def test_remarking_replaces_rather_than_duplicates(self, store):
        store.mark(meta(1), "个股_紫金", "failed", error="boom")
        store.mark(meta(1), "个股_紫金", "done", path="a.md")
        assert store.counts()[0]["done"] == 1 and store.counts()[0]["failed"] == 0

    def test_a_second_store_on_the_same_file_sees_the_state(self, tmp_path, store):
        store.mark(meta(1), "行业_有色金属", "done", path="a.md")
        again = Store(tmp_path / "state" / "db.sqlite")
        try:
            assert again.is_done("id0001xxxx", "行业_有色金属") is True
        finally:
            again.close()


class TestReporting:
    def test_counts_are_per_folder_and_padded(self, store):
        store.mark(meta(1), "个股_紫金", "done", path="a.md")
        store.mark(meta(2), "个股_紫金", "failed", error="boom")
        store.mark(meta(3), "行业_有色金属", "empty")
        assert store.counts() == [
            {"folder": "个股_紫金", "done": 1, "empty": 0, "failed": 1, "filtered": 0},
            {"folder": "行业_有色金属", "done": 0, "empty": 1, "failed": 0, "filtered": 0},
        ]

    def test_counts_can_be_filtered_to_one_folder(self, store):
        store.mark(meta(1), "个股_紫金", "done")
        store.mark(meta(2), "行业_有色", "done")
        assert [c["folder"] for c in store.counts("个股_紫金")] == ["个股_紫金"]

    def test_recent_carries_the_error_for_troubleshooting(self, store):
        store.mark(meta(1), "个股_紫金", "failed", error="BlockedError('风控')")
        rows = store.recent("failed")
        assert rows[0]["error"] == "BlockedError('风控')"
        assert rows[0]["folder"] == "个股_紫金" and rows[0]["id"] == "id0001xxxx"

    def test_recent_honours_folder_and_limit(self, store):
        for n in range(5):
            store.mark(meta(n), "个股_紫金", "failed")
        assert len(store.recent("failed", "个股_紫金", 2)) == 2
        assert store.recent("failed", "行业_有色") == []
