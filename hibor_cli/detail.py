"""Detail page -> Markdown file, and the layout those files live in.

`.abstruct-info` holds the site's own text excerpt of the report, not the PDF: the crawler never
downloads the PDF (that would need the viewer's token flow and is far more likely to trip 风控).
"""
import re
from pathlib import Path

from markdownify import markdownify
from playwright.sync_api import Page, TimeoutError as PWTimeout

from .models import BlockedError, EmptyContentError, LoginRequiredError, ReportMeta

WATERMARK = re.compile(r"https?://www\.hibor\.com\.cn\s*[（(【]?慧博投研资讯[）)】]?")
CONTENT_SEL = ".abstruct-info"
NOT_REPORTS = {"README.md"}  # notes an agent may leave in a folder, never a report to upload


def fetch_content_html(page: Page, url: str) -> str:
    page.goto(url, wait_until="domcontentloaded")
    try:
        # "attached", not "visible": an empty container has zero height and is never visible.
        page.wait_for_selector(CONTENT_SEL, state="attached", timeout=15000)
    except PWTimeout:
        if "login" in page.url.lower():
            raise LoginRequiredError(f"跳转到登录页: {page.url}")
        raise BlockedError(f"正文容器未出现（可能被风控/积分不足/页面异常）: {page.url}")
    if page.evaluate("typeof displayLoginLayer !== 'undefined' && displayLoginLayer === true"):
        raise LoginRequiredError(f"页面要求登录: {page.url}")
    try:
        # The text is filled in by an async request; give it a moment before calling it empty.
        page.wait_for_function(
            "sel => (document.querySelector(sel)?.innerText || '').trim().length > 0",
            arg=CONTENT_SEL, timeout=8000)
    except PWTimeout:
        raise EmptyContentError(f"无文字正文（可能是图片型报告）: {url}")
    return page.inner_html(CONTENT_SEL)


def to_markdown(content_html: str) -> str:
    md = markdownify(content_html, heading_style="ATX")
    md = WATERMARK.sub("", md)
    md = re.sub(r"\[\s*\]\([^)]*\)", "", md)  # empty links left by watermark anchors
    md = re.sub(r"(?m)^[　 ]+", "", md)  # full-width indentation
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def _safe(name: str, limit: int = 80) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" .")[:limit]


_ORG_LIMIT = 24


def report_filename(meta: ReportMeta, suffix: str = "") -> str:
    """慧博的标题本身就是 `<券商>-<标的>-<代码>-<主题>-<研报日>`，所以按它的结构重排而不另造规则：
    开头那段券商挪到末尾，其余原样保留 —— 打开目录先看到标的和主题，券商只在需要区分时才有用。

    `suffix` 只用于标题完全撞车的两篇不同报告（券商爱复用标题），避免后一篇静默覆盖前一篇。
    """
    stem = meta.title
    if meta.org and stem.startswith(f"{meta.org}-"):
        stem = stem[len(meta.org) + 1:] or meta.title
    tail = f"_{suffix}" if suffix else ""
    return f"{_safe(stem)}_{_safe(meta.org, _ORG_LIMIT)}{tail}.md"


def save_markdown(meta: ReportMeta, folder: str, body_md: str, out_dir: Path,
                  label: tuple[str, str], relevance: str = "") -> Path:
    """One file per report, flat inside `folder`. Dates, id and everything else worth knowing are in
    the frontmatter; the filename is for a human scanning the folder."""
    target_dir = out_dir / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / report_filename(meta)
    if path.exists() and f"source: {meta.url}" not in path.read_text(encoding="utf-8", errors="ignore"):
        path = target_dir / report_filename(meta, meta.id[:8])
    label_key, label_value = label
    title = meta.title.replace('"', "'")
    front = ["---", f'title: "{title}"', f"{label_key}: {label_value}"]
    if meta.subject:
        front.append(f'subject: "{meta.subject}"')
    if relevance:
        front.append(f"relevance: {relevance}")
    front += [f"org: {meta.org}", f"published: {meta.published}", f'authors: "{meta.authors}"',
              f"rating: {meta.rating}", f"pages: {meta.pages}", f"source: {meta.url}", "---", ""]
    path.write_text("\n".join(front) + f"# {meta.title}\n\n" + body_md, encoding="utf-8")
    return path


def folders_in(output_dir: Path) -> list[str]:
    """Every saved folder (one per stock or industry), for `push` with no explicit target."""
    if not output_dir.is_dir():
        return []
    return sorted(p.name for p in output_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def reports_in(root: Path) -> list[Path]:
    """Every Markdown report under a folder, notes excluded."""
    return sorted(f for f in root.rglob("*.md") if f.name not in NOT_REPORTS)
