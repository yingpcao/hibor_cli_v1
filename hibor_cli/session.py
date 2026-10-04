"""The persistent Chrome profile IS the login: same browser, same cookies, no token export.

One process may own the profile at a time, so `profile_in_use` is checked before launch and the CLI
answers with exit 6 rather than a Playwright crash. `ctx.request` then rides on that session, which
is the only reason 慧搜's fragment endpoint answers us at all.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .models import ProfileBusyError


@dataclass(frozen=True)
class Session:
    ctx: BrowserContext
    list_page: Page  # stays on the result list so the pager and Referer survive
    detail_page: Page  # navigates report pages


def profile_in_use(profile_dir: Path) -> bool:
    """True if another Chrome already owns the profile (Windows `lockfile`, POSIX `SingletonLock`)."""
    if (profile_dir / "SingletonLock").exists():
        return True
    lock = profile_dir / "lockfile"
    if not lock.exists():
        return False
    try:
        with open(lock, "ab"):
            return False
    except PermissionError:
        return True


def open_context(pw: Playwright, profile_dir: Path, headless: bool = False) -> BrowserContext:
    if profile_in_use(profile_dir):
        raise ProfileBusyError(f"Chrome 配置目录正被另一个进程使用: {profile_dir}"
                               "（关闭登录窗口或其他抓取任务后重试；登录状态本身不会丢）")
    profile_dir.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(profile_dir),
        channel="chrome",
        headless=headless,
        viewport={"width": 1400, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


@contextmanager
def browser_session(profile_dir: Path, headless: bool = False) -> Iterator[Session]:
    with sync_playwright() as pw:
        ctx = open_context(pw, profile_dir, headless=headless)
        try:
            list_page = ctx.pages[0] if ctx.pages else ctx.new_page()
            yield Session(ctx=ctx, list_page=list_page, detail_page=ctx.new_page())
        finally:
            ctx.close()
