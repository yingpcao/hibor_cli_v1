from contextlib import nullcontext
from datetime import datetime

import pytest

from hibor_cli import crawl
from hibor_cli.events import Emitter
from hibor_cli.models import BlockedError, EmptyContentError, LoginRequiredError, ReportMeta
from hibor_cli.session import Session
from hibor_cli.targets import Target


def meta(n: int, title: str = "", subject: str = "", published: str = "2026-09-18") -> ReportMeta:
    return ReportMeta(id=f"id{n:04d}xxxx", url=f"https://x/{n}", title=title or f"报告{n}",
                      published=published, org="o", column="", authors="", rating="", pages="",
                      subject=subject)


def stock_target(**kw) -> Target:
    return Target(kind="stock", name=kw.pop("name", "紫金"), **kw)


def industry_target(**kw) -> Target:
    return Target(kind="industry", name="有色金属", **kw)


def install(monkeypatch, target: Target, metas=(), raises=None):
    """Replace the site walk so the crawl logic is tested without a browser."""
    def fake(ctx, page, tg, start, end, sleep, on_page):
        on_page(1, len(metas))
        if raises:
            raise raises
        yield from metas

    monkeypatch.setattr(crawl, "iter_stock" if target.kind == "stock" else "iter_industry", fake)


def session_factory(_profile=None, _headless=False):
    return nullcontext(Session(ctx=None, list_page=None, detail_page=None))


def ok_fetch(page, url):
    return f"<p>正文 {url} 提到紫金</p>"


def run(settings, target, emitter, fetch=ok_fetch):
    return crawl.fetch_target(settings, target, emitter, session_factory=session_factory, fetch=fetch,
                             sleep=lambda s: None, now=lambda: datetime(2026, 9, 19, 12, 0))


def listit(settings, target, emitter):
    return crawl.list_target(settings, target, emitter, session_factory=session_factory,
                             sleep=lambda s: None, now=lambda: datetime(2026, 9, 19, 12, 0))


@pytest.fixture
def emitter():
    return Emitter(jsonl=False)


class TestIndustryWalk:
    def test_saves_reports_and_reports_paths(self, monkeypatch, settings, emitter):
        install(monkeypatch, industry_target(), [meta(1), meta(2)])
        result = run(settings, industry_target(), emitter)
        assert (result.saved, result.skipped, result.empty, result.failed) == (2, 0, 0, 0)
        assert result.folder == "行业_有色金属"
        assert len(result.saved_paths) == 2
        for path in result.saved_paths:
            assert "正文" in open(path, encoding="utf-8").read()

    def test_second_run_skips_saved(self, monkeypatch, settings, emitter):
        install(monkeypatch, industry_target(), [meta(1), meta(2)])
        run(settings, industry_target(), emitter)
        again = run(settings, industry_target(), emitter, fetch=lambda p, u: pytest.fail("must not refetch"))
        assert (again.saved, again.skipped) == (0, 2)

    def test_empty_body_is_recorded_and_not_retried(self, monkeypatch, settings, emitter):
        install(monkeypatch, industry_target(), [meta(1)])

        def empty(page, url):
            raise EmptyContentError("image only")

        assert (run(settings, industry_target(), emitter, empty).empty,) == (1,)
        second = run(settings, industry_target(), emitter, lambda p, u: pytest.fail("must not retry"))
        assert second.skipped == 1

    def test_isolated_failures_do_not_abort_and_are_retried_next_run(self, monkeypatch, settings, emitter):
        install(monkeypatch, industry_target(), [meta(1), meta(2), meta(3)])
        calls = iter([RuntimeError("boom"), "<p>ok</p>", RuntimeError("boom")])

        def flaky(page, url):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value

        result = run(settings, industry_target(), emitter, flaky)
        assert (result.saved, result.failed) == (1, 2)
        retry = run(settings, industry_target(), emitter)
        assert (retry.saved, retry.skipped) == (2, 1)

    def test_consecutive_failures_abort_as_blocked_and_carry_the_partial(self, monkeypatch, settings, emitter):
        install(monkeypatch, industry_target(), [meta(n) for n in range(10)])
        calls = iter(["<p>ok</p>"] + [RuntimeError("boom")] * 10)

        def flaky(page, url):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value

        with pytest.raises(BlockedError) as excinfo:
            run(settings, industry_target(), emitter, flaky)
        assert excinfo.value.code == "blocked"
        partial = excinfo.value.partial
        assert (partial.saved, partial.failed) == (1, 3)
        assert len(partial.saved_paths) == 1

    def test_session_errors_abort_immediately(self, monkeypatch, settings, emitter):
        install(monkeypatch, industry_target(), [meta(1), meta(2)])
        with pytest.raises(LoginRequiredError) as excinfo:
            run(settings, industry_target(), emitter, lambda p, u: (_ for _ in ()).throw(LoginRequiredError("登录")))
        assert excinfo.value.code == "login_required"
        assert (excinfo.value.partial.saved, excinfo.value.partial.failed) == (0, 0)

    def test_error_raised_mid_walk_still_reports_what_was_done(self, monkeypatch, settings, emitter):
        def then_blocked(ctx, page, tg, start, end, sleep, on_page):
            yield meta(1)
            raise BlockedError("慧搜接口返回 567")

        monkeypatch.setattr(crawl, "iter_industry", then_blocked)
        with pytest.raises(BlockedError) as excinfo:
            run(settings, industry_target(), emitter)
        assert (excinfo.value.partial.saved, excinfo.value.partial.skipped) == (1, 0)

    def test_max_reports_counts_new_saves_only(self, monkeypatch, settings, emitter):
        install(monkeypatch, industry_target(), [meta(n) for n in range(6)])
        run(settings, industry_target(max_reports=2), emitter)
        third = run(settings, industry_target(max_reports=2), emitter)
        assert (third.saved, third.skipped) == (2, 2)  # 已保存的不占本次名额

    def test_list_flags_already_saved(self, monkeypatch, settings, emitter):
        install(monkeypatch, industry_target(), [meta(1), meta(2), meta(3)])
        run(settings, industry_target(max_reports=1), emitter)
        items = listit(settings, industry_target(max_reports=2), emitter)
        assert [i["already_saved"] for i in items] == [True, False]

    def test_result_is_immutable_and_json_friendly(self):
        result = crawl.FetchResult("行业_有色", 1, 0, 0, 0)
        with pytest.raises(AttributeError):
            result.saved = 5
        assert result.to_dict()["saved_paths"] == []


class TestStockGates:
    def test_title_gate_drops_without_paying_for_the_detail(self, monkeypatch, settings, emitter):
        install(monkeypatch, stock_target(), [meta(1, "华鑫期货-锡业有色周报")])
        result = run(settings, stock_target(), emitter, fetch=lambda p, u: pytest.fail("must not request"))
        assert (result.saved, result.filtered, result.failed) == (0, 1, 0)

    def test_filtered_is_recorded_and_not_retried(self, monkeypatch, settings, emitter):
        install(monkeypatch, stock_target(), [meta(1, "无关报告")])
        never = lambda p, u: pytest.fail("must not request")  # noqa: E731
        run(settings, stock_target(), emitter, never)
        again = run(settings, stock_target(), emitter, never)
        assert (again.skipped, again.filtered) == (1, 0)

    def test_body_gate_drops_industry_reports_that_never_mention_the_stock(self, monkeypatch, settings, emitter):
        # 只有宽 scope 会走到正文闸：title scope 在列表页就被标题闸判掉了
        target = stock_target(scope="abstract")
        install(monkeypatch, target, [meta(1, "金属市场观察甲"), meta(2, "金属市场观察乙")])
        bodies = iter(["<p>本期只谈锌价。</p>", "<p>紫金矿业涨 2%。</p>"])
        result = run(settings, target, emitter, lambda p, u: next(bodies))
        assert (result.saved, result.filtered) == (1, 1)
        assert "relevance: industry" in open(result.saved_paths[0], encoding="utf-8").read()

    def test_title_scope_needs_no_detail_request_to_drop_a_false_positive(self, monkeypatch, settings, emitter):
        install(monkeypatch, stock_target(), [meta(1, "金属市场观察甲"), meta(2, "金属市场观察乙")])
        result = run(settings, stock_target(), emitter, lambda p, u: pytest.fail("must not request"))
        assert (result.saved, result.filtered) == (0, 2)

    def test_company_reports_are_kept_whatever_the_body_says(self, monkeypatch, settings, emitter):
        install(monkeypatch, stock_target(), [meta(1, "中信证券-深度报告", "601899(紫金矿业)")])
        result = run(settings, stock_target(), emitter, lambda p, u: "<p>行业整体承压。</p>")
        assert (result.saved, result.filtered) == (1, 0)
        text = open(result.saved_paths[0], encoding="utf-8").read()
        assert 'subject: "601899(紫金矿业)"' in text and "relevance: company" in text
        assert "stock: 紫金" in text

    def test_wide_scope_saves_without_the_title_gate(self, monkeypatch, settings, emitter):
        target = stock_target(scope="abstract")
        install(monkeypatch, target, [meta(1, "有色周报")])
        result = run(settings, target, emitter, lambda p, u: "<p>提到紫金。</p>")
        assert (result.saved, result.filtered) == (1, 0)

    def test_filtered_reports_do_not_use_the_budget(self, monkeypatch, settings, emitter):
        metas = [meta(n, f"无关报告{n}") for n in range(3)] + [meta(n, f"紫金矿业点评{n}") for n in (8, 9)]
        install(monkeypatch, stock_target(), metas)
        result = run(settings, stock_target(max_reports=2), emitter, lambda p, u: "<p>紫金矿业点评</p>")
        assert (result.saved, result.filtered) == (2, 3)

    def test_list_excludes_dropped_items_and_reports_the_verdict(self, monkeypatch, settings, emitter):
        install(monkeypatch, stock_target(), [meta(1, "无关报告"), meta(2, "紫金矿业点评", "601899(紫金矿业)")])
        items = listit(settings, stock_target(), emitter)
        assert [i["relevance"] for i in items] == ["company"]
        assert items[0]["subject"] == "601899(紫金矿业)"

    def test_partial_carries_the_filtered_count(self, monkeypatch, settings, emitter):
        def drop_then_blocked(ctx, page, tg, start, end, sleep, on_page):
            yield meta(1, "无关报告")
            raise BlockedError("慧搜接口返回 567")

        monkeypatch.setattr(crawl, "iter_stock", drop_then_blocked)
        with pytest.raises(BlockedError) as excinfo:
            run(settings, stock_target(), emitter)
        assert excinfo.value.partial.filtered == 1


class TestEvents:
    def test_jsonl_stream_is_valid_json_lines(self, monkeypatch, settings, capsys):
        import json

        install(monkeypatch, industry_target(), [meta(1)])
        run(settings, industry_target(), Emitter(jsonl=True))
        events = [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()]
        assert events[:3] == ["start", "page", "saved"] and events[-1] == "done"

    def test_start_event_names_the_folder_and_scope(self, monkeypatch, settings, capsys):
        import json

        install(monkeypatch, stock_target(scope="fulltext"), [meta(1)])
        run(settings, stock_target(scope="fulltext"), Emitter(jsonl=True))
        start = json.loads(capsys.readouterr().out.splitlines()[0])
        assert (start["folder"], start["scope"], start["max_reports"]) == ("个股_紫金", "fulltext", 100)
