"""List walkers and detail fetching, exercised against fakes (no network, no browser)."""
import re
from datetime import datetime

import pytest

from hibor_cli import session as session_module
from hibor_cli.detail import fetch_content_html
from hibor_cli.industry import iter_industry
from hibor_cli.models import BlockedError, EmptyContentError, LoginRequiredError, ProfileBusyError
from hibor_cli.search import SA_URL as SEARCH_SA_URL, iter_stock
from hibor_cli.targets import Target
from tests.fakes import FakeContext, FakeDetailPage, FakePage, FakeRequest, FakeResponse

START, END = datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59)


def record():
    sleeps, pages = [], []
    return sleeps, pages, sleeps.append, lambda n, t: pages.append((n, t))


class TestIterStock:
    target = Target(kind="stock", name="白银")

    def older(self, html: str) -> str:
        return re.sub(r"2026-09-\d\d", "2026-08-01", html)

    def test_walks_pages_until_a_page_is_older_than_start(self, fixture_text):
        page1 = fixture_text("search_sa.html")
        req = FakeRequest([FakeResponse(200, page1), FakeResponse(200, self.older(page1))])
        sleeps, pages, sleep, on_page = record()
        items = list(iter_stock(FakeContext(req), FakePage(), self.target, START, END, sleep, on_page))
        assert len(items) == 10  # 第二页整页都超出范围，不浪费第三次请求
        assert len(req.calls) == 2
        assert pages == [(1, 365), (2, 365)] and sleeps == ["page"]
        assert req.calls[0]["url"] == SEARCH_SA_URL

    def test_request_carries_scope_page_number_and_referer(self, fixture_text):
        req = FakeRequest([FakeResponse(200, self.older(fixture_text("search_sa.html")))])
        list(iter_stock(FakeContext(req), FakePage(url="https://x/ref"), self.target, START, END,
                        str, lambda n, t: None))
        call = req.calls[0]
        assert call["form"]["gjc"] == "白银" and call["form"]["cxzd"] == "bt"
        assert call["form"]["ys"] == "1" and call["form"]["px"] == "sj"
        assert call["headers"]["Referer"] == "https://x/ref"

    @pytest.mark.parametrize("scope, cxzd", [("title", "bt"), ("abstract", "zy"), ("fulltext", "qw")])
    def test_scope_maps_to_the_site_dropdown(self, fixture_text, scope, cxzd):
        req = FakeRequest([FakeResponse(200, self.older(fixture_text("search_sa.html")))])
        target = Target(kind="stock", name="k", scope=scope)
        list(iter_stock(FakeContext(req), FakePage(), target, START, END, str, lambda n, t: None))
        assert req.calls[0]["form"]["cxzd"] == cxzd

    def test_stops_after_last_page_by_total(self, fixture_text):
        html = re.sub(r'hidTotal" value="\d+"', 'hidTotal" value="10"', fixture_text("search_sa.html"))
        req = FakeRequest([FakeResponse(200, html)])
        items = list(iter_stock(FakeContext(req), FakePage(), self.target, START, END, str, lambda n, t: None))
        assert len(items) == 10 and len(req.calls) == 1

    def test_items_outside_end_are_filtered(self, fixture_text):
        page1 = fixture_text("search_sa.html")
        req = FakeRequest([FakeResponse(200, page1), FakeResponse(200, self.older(page1))])
        items = list(iter_stock(FakeContext(req), FakePage(), self.target, START,
                                datetime(2026, 9, 18, 23, 59), str, lambda n, t: None))
        assert items and all(i.published <= "2026-09-18" for i in items)

    def test_http_error_is_blocked(self):
        req = FakeRequest([FakeResponse(403, "denied")])
        with pytest.raises(BlockedError, match="403"):
            list(iter_stock(FakeContext(req), FakePage(), self.target, START, END, str, lambda n, t: None))

    def test_login_redirect(self):
        with pytest.raises(LoginRequiredError):
            list(iter_stock(FakeContext(FakeRequest([])),
                            FakePage(url="https://www.hibor.com.cn/login.html"),
                            self.target, START, END, str, lambda n, t: None))

    def test_empty_result_ends_quietly(self):
        req = FakeRequest([FakeResponse(200, '<input id="hidTotal" value="0">')])
        assert list(iter_stock(FakeContext(req), FakePage(), self.target, START, END,
                               str, lambda n, t: None)) == []


class TestIterIndustry:
    target = Target(kind="industry", name="有色金属")

    def second_page(self, html: str) -> str:
        html = html.replace("607d8c7f295a1328b9c465fe00b21cce", "aaaa8c7f295a1328b9c465fe00b21cce")
        html = html.replace("0cb12e8817f1f33384d7e4de6c14fbca", "bbbb2e8817f1f33384d7e4de6c14fbca")
        return re.sub(r"2026-09-\d\d", "2026-08-01", html)

    def walk(self, page, target=None, start=START):
        sleeps, pages, sleep, on_page = record()
        return list(iter_industry(None, page, target or self.target, start, END, sleep, on_page)), sleeps, pages

    def test_pages_forward_and_stops_at_older_page(self, fixture_text):
        html = fixture_text("industry_list.html")
        items, sleeps, pages = self.walk(FakePage([html, self.second_page(html)]))
        assert len(items) == 2
        assert pages == [(1, None), (2, None)] and sleeps == ["page"]

    def test_stops_when_next_does_not_advance(self, fixture_text):
        items, _, pages = self.walk(FakePage([fixture_text("industry_list.html")], advances=False))
        assert len(items) == 2 and pages == [(1, None)]

    def test_single_page_without_next_button(self, fixture_text):
        items, sleeps, _ = self.walk(FakePage([fixture_text("industry_list.html")]))
        assert len(items) == 2 and sleeps == []

    def test_fills_query_form(self, fixture_text):
        page = FakePage([fixture_text("industry_list.html")])
        target = Target(kind="industry", name="有色金属", sub_industry="工业金属", title_keyword="周报")
        self.walk(page, target)
        assert ("select", "#f1_hy1", "有色金属") in page.calls
        assert ("select", "#f1_hy2", "工业金属") in page.calls
        assert ("fill", "#f1_ybbt", "周报") in page.calls
        assert ("click", "input.hyfx-btn") in page.calls

    def test_empty_result_page(self):
        assert self.walk(FakePage(["<html></html>"]))[0] == []

    def test_login_redirect(self):
        with pytest.raises(LoginRequiredError):
            self.walk(FakePage(["<html></html>"], url="https://www.hibor.com.cn/login.html"))

    def test_blank_page_without_query_form_is_blocked_not_internal_error(self):
        page = FakePage(["<html><head></head><body></body></html>"], form_present=False)
        with pytest.raises(BlockedError, match="空白页"):
            self.walk(page)
        assert not any(call[0] == "select" for call in page.calls)  # never tried to use the missing form

    def test_missing_form_on_login_url_is_login_required(self):
        with pytest.raises(LoginRequiredError):
            self.walk(FakePage(["<html></html>"], url="https://www.hibor.com.cn/login.html", form_present=False))


class TestFetchContentHtml:
    def test_returns_container_html(self):
        assert fetch_content_html(FakeDetailPage(html="<p>x</p>"), "u") == "<p>x</p>"

    def test_missing_container_is_blocked(self):
        with pytest.raises(BlockedError):
            fetch_content_html(FakeDetailPage(container=False), "u")

    def test_missing_container_on_login_url_is_login_required(self):
        with pytest.raises(LoginRequiredError):
            fetch_content_html(FakeDetailPage(container=False, url="https://www.hibor.com.cn/login.html"), "u")

    def test_login_layer(self):
        with pytest.raises(LoginRequiredError):
            fetch_content_html(FakeDetailPage(login_layer=True), "u")

    def test_empty_body_is_not_a_session_error(self):
        with pytest.raises(EmptyContentError):
            fetch_content_html(FakeDetailPage(has_text=False), "u")


class TestProfileInUse:
    """The profile is the login: two processes on it would corrupt the session, so one must lose."""

    def test_no_profile_dir(self, tmp_path):
        assert session_module.profile_in_use(tmp_path / "missing") is False

    def test_posix_singleton_lock(self, tmp_path):
        (tmp_path / "SingletonLock").write_text("")
        assert session_module.profile_in_use(tmp_path) is True

    def test_unlocked_lockfile(self, tmp_path):
        (tmp_path / "lockfile").write_bytes(b"")
        assert session_module.profile_in_use(tmp_path) is False

    def test_locked_lockfile_windows(self, tmp_path, monkeypatch):
        lock = tmp_path / "lockfile"
        lock.write_bytes(b"")
        real_open = open

        def deny(path, *a, **k):
            if str(path) == str(lock):
                raise PermissionError
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", deny)
        assert session_module.profile_in_use(tmp_path) is True

    def test_open_context_refuses_a_busy_profile(self, tmp_path):
        (tmp_path / "SingletonLock").write_text("")
        with pytest.raises(ProfileBusyError, match="另一个进程"):
            session_module.open_context(None, tmp_path)
