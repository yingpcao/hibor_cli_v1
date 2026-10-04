"""Run a target: list -> dedupe -> relevance -> detail -> md. `list_target` is the same walk without downloading.

Everything injectable (session factory, detail fetcher, sleep, clock) is a parameter, so the tests
drive the whole flow against stored HTML and this module is never the untestable part.
"""
import random
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .detail import fetch_content_html, save_markdown, to_markdown
from .events import Emitter
from .industry import iter_industry
from .models import BlockedError, EmptyContentError, ReportMeta, SessionError
from .relevance import DROP, body_verdict, list_verdict
from .search import iter_stock
from .session import Session, browser_session
from .store import Store
from .targets import Target, resolve_range

SessionFactory = Callable[[Path, bool], AbstractContextManager[Session]]


@dataclass(frozen=True)
class FetchResult:
    folder: str
    saved: int
    skipped: int
    empty: int
    failed: int
    filtered: int = 0  # judged irrelevant to the stock; recorded, not saved
    saved_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "saved_paths": list(self.saved_paths)}


def _walk(settings: Settings, target: Target, session: Session, emit: Emitter,
          sleep: Callable[[float], None], now: datetime) -> Iterator[ReportMeta]:
    start, end = resolve_range(target.date_range, now)
    delay = settings.delay
    emit.event("start", f"[{target.kind}] {target.folder} {start:%F} ~ {end:%F}, 上限 {target.max_reports} 篇",
               kind=target.kind, folder=target.folder, start=f"{start:%F}", end=f"{end:%F}",
               max_reports=target.max_reports, scope=target.scope)

    def pause(kind: str) -> None:
        sleep(random.uniform(*getattr(delay, kind)))

    def on_page(page_no: int, total: int | None) -> None:
        emit.event("page", f"  [第 {page_no} 页]" + (f" 共 {total} 条" if total is not None else ""),
                   page=page_no, total=total)

    walk = iter_stock if target.kind == "stock" else iter_industry
    return walk(session.ctx, session.list_page, target, start, end, pause, on_page)


def _emit_filtered(emit: Emitter, meta: ReportMeta, reason: str) -> None:
    emit.event("filtered", f"  ~~ 丢弃 {meta.title[:40]}: {reason}", id=meta.id, title=meta.title, reason=reason)


def list_target(settings: Settings, target: Target, emit: Emitter, *,
                session_factory: SessionFactory = browser_session,
                sleep: Callable[[float], None] = time.sleep,
                now: Callable[[], datetime] = datetime.now) -> list[dict[str, Any]]:
    """Enumerate what a fetch would look at (up to max_reports), flagging what is already saved.
    Items the relevance gates would drop are left out (and reported as `filtered` events)."""
    store = Store(settings.db_path)
    try:
        with session_factory(settings.profile_dir, settings.headless) as session:
            items: list[dict[str, Any]] = []
            for meta in _walk(settings, target, session, emit, sleep, now()):
                if len(items) >= target.max_reports:
                    break
                verdict, reason = list_verdict(meta, target)
                if verdict == DROP:
                    _emit_filtered(emit, meta, reason)
                    continue
                items.append({**asdict(meta), "already_saved": store.is_done(meta.id, target.folder),
                              "relevance": verdict})
            return items
    finally:
        store.close()


def fetch_target(settings: Settings, target: Target, emit: Emitter, *,
                 session_factory: SessionFactory = browser_session,
                 fetch: Callable[..., str] = fetch_content_html,
                 sleep: Callable[[float], None] = time.sleep,
                 now: Callable[[], datetime] = datetime.now) -> FetchResult:
    delay = settings.delay
    saved = skipped = empty = failed = filtered = failures_in_row = 0
    paths: list[str] = []
    store = Store(settings.db_path)
    try:
        with session_factory(settings.profile_dir, settings.headless) as session:
            try:
                for meta in _walk(settings, target, session, emit, sleep, now()):
                    if saved + failed >= target.max_reports:
                        break
                    if store.is_done(meta.id, target.folder):
                        skipped += 1
                        emit.event("skipped", id=meta.id, title=meta.title, reason="already_saved")
                        continue
                    verdict, reason = list_verdict(meta, target)
                    if verdict == DROP:
                        # 列表页就判掉了，不必为它付一次详情页请求，也不占 max_reports 名额
                        store.mark(meta, target.folder, "filtered", error=reason)
                        filtered += 1
                        _emit_filtered(emit, meta, reason)
                        continue
                    try:
                        body = to_markdown(fetch(session.detail_page, meta.url))
                        keep, reason = body_verdict(body, target, verdict)
                        if not keep:
                            store.mark(meta, target.folder, "filtered", error=reason)
                            filtered += 1
                            _emit_filtered(emit, meta, reason)
                        else:
                            path = save_markdown(meta, target.folder, body, settings.output_dir,
                                                 target.label, verdict)
                            store.mark(meta, target.folder, "done", str(path))
                            saved, failures_in_row = saved + 1, 0
                            paths.append(str(path))
                            emit.event("saved", f"  OK {meta.published[:10]} {meta.title[:40]}",
                                       id=meta.id, title=meta.title, published=meta.published, path=str(path))
                    except SessionError:
                        raise
                    except EmptyContentError as exc:
                        store.mark(meta, target.folder, "empty", error=str(exc))
                        empty += 1
                        emit.event("empty", f"  -- 无文字正文，跳过: {meta.title[:40]}", id=meta.id, title=meta.title)
                    except Exception as exc:  # per-report failure, keep going
                        store.mark(meta, target.folder, "failed", error=repr(exc))
                        failed, failures_in_row = failed + 1, failures_in_row + 1
                        emit.event("failed", f"  FAIL {meta.title[:40]}: {exc!r}",
                                   id=meta.id, title=meta.title, error=repr(exc))
                        if failures_in_row >= settings.max_consecutive_failures:
                            raise BlockedError(f"连续失败 {failures_in_row} 次，停止（可能被风控）") from exc
                    done = saved + failed
                    if done and done % delay.batch_size == 0:
                        sleep(random.uniform(*delay.batch_pause))
                    else:
                        sleep(random.uniform(*delay.detail))
            except Exception as exc:  # aborted mid-walk (login/blocked/3-in-a-row/unexpected):
                # the work already done travels on the exception; the CLI puts it in the envelope
                exc.partial = FetchResult(target.folder, saved, skipped, empty, failed, filtered, tuple(paths))
                raise
    finally:
        store.close()
    result = FetchResult(target.folder, saved, skipped, empty, failed, filtered, tuple(paths))
    emit.event("done", f"[{target.folder}] 完成 saved={saved} skipped={skipped} empty={empty} "
                       f"filtered={filtered} failed={failed}")
    return result
