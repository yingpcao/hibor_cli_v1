"""行业 report list: pick the category on the query form, then walk the pages. Newest first.

The site gives no date filter here, so the range is applied page by page and the walk stops as soon
as a whole page predates `start` (the list is sorted newest-first).
"""
import json
import re
from collections.abc import Callable, Iterator
from datetime import datetime

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .models import BlockedError, LoginRequiredError, ReportMeta
from .targets import Target

LIST_URL = "https://www.hibor.com.cn/newweb/web/hangye"
BASE = "https://www.hibor.com.cn"


def _field(block: Tag, label: str) -> str:
    for span in block.select("div.tab_divtxt > span"):
        text = span.get_text(strip=True)
        if text.startswith(label):
            return text.split("：", 1)[1] if "：" in text else ""
    return ""


def parse_list(html: str) -> list[ReportMeta]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for head in soup.select("div.tab_divttl"):
        a = head.select_one("a[href*='/data/']")
        if not a:
            continue
        block = head.parent
        title = a.get("title") or a.get_text(strip=True)
        href = a["href"]
        url = BASE + href if href.startswith("/") else href
        rid = re.search(r"/data/([0-9a-f]+)\.html", url)
        out.append(ReportMeta(
            id=rid.group(1) if rid else url, url=url, title=title,
            published=_field(block, "分享时间"), org=title.split("-", 1)[0],
            column=_field(block, "栏目"), authors=_field(block, "作者"),
            rating=_field(block, "评级"), pages=_field(block, "页数"),
        ))
    return out


def parse_industries(html: str) -> list[dict]:
    """Industry categories and their sub-industries, as the query form offers them."""
    soup = BeautifulSoup(html, "lxml")
    names = [o.get("value") for o in soup.select("#f1_hy1 option") if o.get("value") not in (None, "all")]
    found = re.search(r"hangYe2\s*=\s*eval\('\((\{.*?\})\)'\)", html, re.S)
    subs = json.loads(found.group(1)) if found else {}
    return [{"name": n, "sub_industries": subs.get(n, [])} for n in names]


def _parse_dt(text: str) -> datetime:
    return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")


def iter_industry(ctx: BrowserContext, page: Page, target: Target, start: datetime, end: datetime,
                  sleep: Callable[[str], None], on_page: Callable[[int, int | None], None] = lambda n, t: None,
                  ) -> Iterator[ReportMeta]:
    page.goto(LIST_URL, wait_until="networkidle")
    try:
        page.wait_for_selector("#f1_hy1", timeout=15000)
    except PWTimeout:
        if "login" in page.url.lower():
            raise LoginRequiredError(f"行业页跳转到登录页: {page.url}")
        # HTTP 200 with an empty document is how the site answers a throttled client
        raise BlockedError("行业页没有出现查询表单（空白页，疑似被限流）")
    page.select_option("#f1_hy1", target.name)
    if target.sub_industry:
        page.select_option("#f1_hy2", target.sub_industry)
    if target.title_keyword:
        page.fill("#f1_ybbt", target.title_keyword)
    page.click("input.hyfx-btn")
    page.wait_for_load_state("networkidle")

    page_no = 1
    while True:
        if "login" in page.url.lower():
            raise LoginRequiredError(f"列表页跳转到登录页: {page.url}")
        items = parse_list(page.content())
        on_page(page_no, None)
        if not items:
            return
        stamps = [_parse_dt(i.published) for i in items if i.published]
        for item in items:
            if item.published and start <= _parse_dt(item.published) <= end:
                yield item
        if stamps and max(stamps) < start:
            return  # whole page is older than the range
        nxt = page.locator("a:has-text('下一页')")
        if not nxt.count():
            return
        sleep("page")
        nxt.first.click()
        page.wait_for_load_state("networkidle")
        if [i.id for i in parse_list(page.content())] == [i.id for i in items]:
            return  # last page: "next" did not advance
        page_no += 1
