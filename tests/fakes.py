"""Minimal stand-ins for the Playwright objects the crawler touches."""
import re
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import TimeoutError as PWTimeout


@dataclass
class FakeResponse:
    status: int
    body: str

    def text(self) -> str:
        return self.body


@dataclass
class FakeRequest:
    responses: list[FakeResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def post(self, url: str, form: dict, headers: dict) -> FakeResponse:
        self.calls.append({"url": url, "form": form, "headers": headers})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


@dataclass
class FakeContext:
    request: FakeRequest


class _Locator:
    def __init__(self, page: "FakePage", exists: bool):
        self._page, self._exists = page, exists
        self.first = self

    def count(self) -> int:
        return 1 if self._exists else 0

    def click(self) -> None:
        self._page.advance()


class FakePage:
    """Serves a list of HTML pages; clicking '下一页' moves to the next one."""

    def __init__(self, pages: list[str] | None = None, url: str = "https://www.hibor.com.cn/x",
                 advances: bool = True, text: dict[str, int] | None = None, body_text: str = "x",
                 form_present: bool = True):
        self.pages, self.index, self.url, self.advances = pages or [""], 0, url, advances
        self.form_present = form_present
        self.calls: list[tuple] = []
        self._text_counts, self._body = text or {}, body_text

    def advance(self) -> None:
        if self.advances and self.index < len(self.pages) - 1:
            self.index += 1

    def goto(self, url: str, **kw) -> None:
        self.calls.append(("goto", url))

    def wait_for_selector(self, sel: str, **kw) -> None:
        if not self.form_present:
            raise PWTimeout("selector never appeared")

    def select_option(self, sel: str, value: str) -> None:
        self.calls.append(("select", sel, value))

    def fill(self, sel: str, value: str) -> None:
        self.calls.append(("fill", sel, value))

    def click(self, sel: str) -> None:
        self.calls.append(("click", sel))

    def wait_for_load_state(self, *a, **kw) -> None: ...

    def wait_for_timeout(self, ms: int) -> None: ...

    def content(self) -> str:
        return self.pages[self.index]

    def inner_text(self, sel: str) -> str:
        return self._body

    def locator(self, sel: str) -> _Locator:
        if "下一页" in sel:
            return _Locator(self, self.index < len(self.pages) - 1 or not self.advances)
        match = re.search(r"text=(.+)", sel)
        return _Locator(self, bool(match and self._text_counts.get(match.group(1))))


class FakeDetailPage:
    """Detail page whose behaviour is chosen per test."""

    def __init__(self, *, container: bool = True, login_layer: bool = False, has_text: bool = True,
                 html: str = "<p>正文</p>", url: str = "https://www.hibor.com.cn/data/a.html"):
        self.container, self.login_layer, self.has_text, self.html, self.url = container, login_layer, has_text, html, url

    def goto(self, url: str, **kw) -> None: ...

    def wait_for_selector(self, sel: str, **kw) -> None:
        if not self.container:
            raise PWTimeout("no container")

    def evaluate(self, script: str) -> bool:
        return self.login_layer

    def wait_for_function(self, script: str, **kw) -> None:
        if not self.has_text:
            raise PWTimeout("empty")

    def inner_html(self, sel: str) -> str:
        return self.html
