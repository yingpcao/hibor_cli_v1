"""慧搜 search for one stock: page through the `/HuiSou/sa` HTML fragment endpoint. Newest first."""
import math
import re
from collections.abc import Callable, Iterator
from datetime import date, datetime
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page

from .models import BlockedError, LoginRequiredError, ReportMeta
from .targets import Target

BASE = "https://www.hibor.com.cn"
SEARCH_PAGE = BASE + "/newweb/HuiSou/s"
SA_URL = BASE + "/newweb/HuiSou/sa"
PAGE_SIZE = 10

# (max days back, sjfw value) — the site only accepts these presets, so we ask for the smallest one
# covering the range and trim the rest locally.
_WINDOWS: tuple[tuple[int, str], ...] = (
    (1, "-1"), (3, "-3"), (7, "-7"), (31, "1"), (92, "3"), (183, "6"), (366, "12"),
)
_WIDEST = "24"


def pick_window(start: datetime, today: date) -> str:
    """Smallest site preset that fully covers [start, today] (one day of margin)."""
    days_back = (today - start.date()).days + 1
    for limit, value in _WINDOWS:
        if days_back <= limit:
            return value
    return _WIDEST


def _form(keyword: str, sjfw: str, page_no: int, cxzd: str) -> dict[str, str]:
    return {"gjc": keyword, "sslb": "1", "sjfw": sjfw, "ys": str(page_no), "cxzd": cxzd,
            "px": "sj", "bgfl": "", "bgys": "", "gs": "", "sdgs": "", "sdhy": "", "sdhgcl": "",
            "mhss": "", "hy": "", "gp": ""}


def parse_results(html: str) -> tuple[int, list[ReportMeta]]:
    soup = BeautifulSoup(html, "lxml")
    total_el = soup.select_one("#hidTotal")
    if total_el is None:
        raise BlockedError("慧搜返回内容缺少 hidTotal（可能登录失效或被风控）")
    items = []
    for node in soup.select(".result-dataitem"):
        a = node.select_one("a[href*='/data/']")
        if not a:
            continue
        head, tail = (
            [s.get_text(strip=True) for s in row.select("span")] for row in node.select(".result-data1")[:2]
        )
        href = a["href"]
        url = BASE + href if href.startswith("/") else href
        rid = re.search(r"/data/([0-9a-f]+)\.html", url)
        title = a.get_text(strip=True)
        items.append(ReportMeta(
            id=rid.group(1) if rid else url, url=url, title=title,
            published=tail[0] if tail else "", org=(head[2] if len(head) > 2 else "") or title.split("-", 1)[0],
            column=head[0] if head else "", authors=head[3] if len(head) > 3 else "",
            rating="", pages=tail[3] if len(tail) > 3 else "",
            subject=head[1] if len(head) > 1 else "",  # the only place the site names the subject stock
        ))
    return int(total_el.get("value") or 0), items


def _day(text: str) -> date:
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def iter_stock(ctx: BrowserContext, page: Page, target: Target, start: datetime, end: datetime,
               sleep: Callable[[str], None], on_page: Callable[[int, int | None], None] = lambda n, t: None,
               ) -> Iterator[ReportMeta]:
    sjfw = pick_window(start, date.today())
    cxzd = target.cxzd
    # Visit the real page once: sets Referer/cookies exactly as a user would.
    query = urlencode({"gjc": target.name, "sslb": "1", "sjfw": sjfw, "cxzd": cxzd, "px": "sj"})
    page.goto(f"{SEARCH_PAGE}?{query}", wait_until="networkidle")
    if "login" in page.url.lower():
        raise LoginRequiredError(f"慧搜跳转到登录页: {page.url}")

    page_no = 1
    while True:
        resp = ctx.request.post(SA_URL, form=_form(target.name, sjfw, page_no, cxzd),
                                headers={"Referer": page.url, "X-Requested-With": "XMLHttpRequest"})
        if resp.status != 200:
            raise BlockedError(f"慧搜接口返回 {resp.status}")
        total, items = parse_results(resp.text())
        on_page(page_no, total)
        for item in items:
            if item.published and start.date() <= _day(item.published) <= end.date():
                yield item
        oldest = min((_day(i.published) for i in items if i.published), default=None)
        if not items or page_no >= math.ceil(total / PAGE_SIZE) or (oldest and oldest < start.date()):
            return  # 结果按时间倒序，这一页最旧的一条已经超出范围，后面不必再翻
        page_no += 1
        sleep("page")
