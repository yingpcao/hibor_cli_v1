"""hibor command line. Written for agents: stdout is JSON only, progress goes to stderr.

    hibor stock fetch 紫金 --days 30 --max 20
    hibor stock list 紫金矿业 --scope abstract --days 30
    hibor industry list 有色金属 --sub 稀有金属 --days 7
    hibor push --kb 投研资料 --stock 紫金
    hibor spec                      # 机器可读的命令契约（参数、退出码、信封）
    hibor init                      # 首次安装后写出 ~/.hibor/config.yaml

`hibor` 是系统级命令（`uv tool install`），任意目录都能跑；配置按 `--config` >
`HIBOR_CONFIG` > `./config.yaml` > `~/.hibor/config.yaml` 找，找不到就报退出码 2 并告诉你怎么办。

Exit codes: 0 ok | 1 internal error | 2 usage/config | 3 login required | 4 blocked (WAF/quota/odd page)
            5 finished, but something needs attention (failed reports) | 6 Chrome profile busy
"""
import argparse
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from . import weknora, __version__
from .config import (CONFIG_FILENAME, USER_CONFIG_DIR, Settings, load_config, resolve_config_path,
                     write_config)
from .crawl import FetchResult, fetch_target, list_target
from .detail import folders_in
from .events import Emitter
from .industry import LIST_URL, parse_industries
from .models import BlockedError, ConfigError, HiborError
from .session import browser_session, open_context, profile_in_use
from .spec import CONFIGLESS_COMMANDS, EXIT_CODES, SPEC
from .store import Store
from .targets import (DEFAULT_MAX, DEFAULT_RANGE, INDUSTRY_PREFIX, SCOPES, STOCK_PREFIX, Target)

@dataclass(frozen=True)
class Outcome:
    data: Any = None
    error: dict[str, str] | None = None

    @property
    def exit_code(self) -> int:
        return EXIT_CODES["ok"] if self.error is None else EXIT_CODES.get(self.error["code"], 1)


Handler = Callable[[argparse.Namespace, Settings | None, Emitter], Outcome]


def _target(args: argparse.Namespace) -> Target:
    if args.start:
        date_range: Any = {"start": args.start, **({"end": args.end} if args.end else {})}
    else:
        date_range = f"last_{args.days}_days" if args.days else DEFAULT_RANGE
    common = {"date_range": date_range, "max_reports": args.max or DEFAULT_MAX}
    if args.command == "industry":
        return Target(kind="industry", name=args.name, sub_industry=args.sub or "",
                      title_keyword=args.keyword or "", **common)
    return Target(kind="stock", name=args.name, scope=args.scope,
                  keep_noise=args.keep_noise, **common)


def _outcome_for(result: FetchResult) -> Outcome:
    if result.failed:
        return Outcome(result.to_dict(), {"code": "partial_failure", "message": f"{result.failed} 篇抓取失败"})
    return Outcome(result.to_dict())


def cmd_fetch(args, settings, emit) -> Outcome:
    return _outcome_for(fetch_target(settings, _target(args), emit))


def cmd_list(args, settings, emit) -> Outcome:
    target = _target(args)
    items = list_target(settings, target, emit)
    return Outcome({"folder": target.folder, "count": len(items),
                    "new": sum(not i["already_saved"] for i in items), "items": items})


def cmd_status(args, settings, emit) -> Outcome:
    store = Store(settings.db_path)
    try:
        # 同一条命令在不同 cwd 下可能解析到不同工作区，所以把用的配置也报出来
        data: dict[str, Any] = {"config_path": str(settings.config_path),
                                "folders": store.counts(args.folder)}
        if args.failed:
            data["failed"] = store.recent("failed", args.folder, args.limit)
        return Outcome(data)
    finally:
        store.close()


def _push_targets(args, settings) -> list[str]:
    """`--stock/--industry` name the folders directly; with neither, push covers everything saved."""
    names = ([f"{STOCK_PREFIX}{n}" for n in args.stock or []]
             + [f"{INDUSTRY_PREFIX}{n}" for n in args.industry or []])
    if not names:
        names = folders_in(settings.output_dir)
    if not names:
        raise ConfigError(f"{settings.output_dir} 下没有已抓取的分组，先运行 fetch")
    missing = [n for n in names if not (settings.output_dir / n).is_dir()]
    if missing:
        raise ConfigError(f"分组目录不存在: {missing}；已抓取的分组: {folders_in(settings.output_dir)}")
    return names


def cmd_push(args, settings, emit) -> Outcome:
    """Upload saved Markdown to a WeKnora knowledge base. No browser, no hibor traffic."""
    client = weknora.make_client(settings.weknora)
    kb = weknora.pick_kb(client, args.kb, create=args.create, description=args.description or "")
    results = [weknora.push(client, kb, settings.output_dir / name, emit,
                            dry_run=args.dry_run, timeout=args.timeout) for name in _push_targets(args, settings)]
    failed = [{"folder": r["folder"], **f} for r in results for f in r["failed"]]
    data = {"kb": {"id": kb["id"], "name": kb.get("name", "")}, "dry_run": args.dry_run,
            "uploaded": sum(len(r["uploaded"]) for r in results),
            "completed": sum(r.get("completed", 0) for r in results),
            "already_in_kb": sum(r["already_in_kb"] for r in results),
            "failed": failed, "folders": results}
    if failed:
        return Outcome(data, {"code": "partial_failure",
                              "message": f"{len(failed)} 篇上传或解析未成功，详见 data.failed"})
    return Outcome(data)


def cmd_doctor(args, settings, emit) -> Outcome:
    data: dict[str, Any] = {"config_path": str(settings.config_path),
                            "profile_dir": str(settings.profile_dir),
                            "profile_busy": profile_in_use(settings.profile_dir),
                            "logged_in": None, "blocked": None}
    if data["profile_busy"]:
        return Outcome(data, {"code": "profile_busy", "message": "Chrome 配置目录被占用，无法检查登录态"})
    with browser_session(settings.profile_dir, settings.headless) as session:
        page = session.list_page
        page.goto(LIST_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        data["blocked"] = not page.inner_text("body").strip()
        data["logged_in"] = page.locator("text=退出登录").count() > 0
    if data["blocked"]:
        return Outcome(data, {"code": "blocked", "message": "行业页返回空白页，疑似被限流，稍后再试"})
    if not data["logged_in"]:
        return Outcome(data, {"code": "login_required", "message": "未登录，请运行 `hibor login`"})
    return Outcome(data)


def cmd_industries(args, settings, emit) -> Outcome:
    with browser_session(settings.profile_dir, settings.headless) as session:
        session.list_page.goto(LIST_URL, wait_until="networkidle")
        industries = parse_industries(session.list_page.content())
    if not industries:
        raise BlockedError("行业页没有返回行业列表（空白页或被限流）")
    return Outcome({"industries": industries})


def cmd_login(args, settings, emit) -> Outcome:
    """The only step that needs a human: log in once, the profile keeps the session."""
    with sync_playwright() as pw:
        ctx = open_context(pw, settings.profile_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LIST_URL)
        emit.event("login", "请在打开的浏览器里登录慧博；登录成功后关闭浏览器窗口。")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:  # window closed / driver went away: nothing left to wait for
            pass
    return Outcome({"profile": str(settings.profile_dir), "saved": True})


def cmd_init(args, settings, emit) -> Outcome:
    """系统级安装后的第一步：把配置模板写到用户目录，之后所有命令都不必再带 --config。"""
    path = write_config(Path(args.path) if args.path else USER_CONFIG_DIR / CONFIG_FILENAME,
                        profile_dir=args.profile_dir, force=args.force)
    return Outcome({"config": str(path), "profile_dir": str(args.profile_dir or "chrome-profile"),
                    "next": ["hibor login（开浏览器，人工登录一次）", "hibor doctor"]})


def cmd_spec(args, settings, emit) -> Outcome:
    """The machine-readable contract: commands, flags, defaults, exit codes, envelope shape."""
    data: dict[str, Any] = {**SPEC, "version": __version__}
    try:
        data["config_path"] = str(resolve_config_path(args.config))
    except ConfigError as exc:
        data["config_path"] = None
        data["config_error"] = str(exc)
    return Outcome(data)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="PATH",
                        help="config.yaml 路径；不指定时按 HIBOR_CONFIG > ./config.yaml > ~/.hibor/config.yaml 找")
    stream = argparse.ArgumentParser(add_help=False)
    stream.add_argument("--jsonl", action="store_true", help="stdout 输出事件流（每行一个 JSON），末行为 result")
    window = argparse.ArgumentParser(add_help=False)
    window.add_argument("--days", type=int, help=f"最近 N 天（默认 {DEFAULT_RANGE}）")
    window.add_argument("--from", dest="start", metavar="YYYY-MM-DD")
    window.add_argument("--to", dest="end", metavar="YYYY-MM-DD")
    window.add_argument("--max", type=int, help=f"最多处理篇数（默认 {DEFAULT_MAX}）")

    parser = argparse.ArgumentParser(prog="hibor", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"hibor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = argparse.ArgumentParser(add_help=False)
    crawl.add_argument("name", help="个股简称/代码，或行业大类名（见 `hibor industries`）")
    for kind, help_text in (("stock", "个股研报（慧搜检索）"), ("industry", "行业研报（行业列表页）")):
        actions = sub.add_parser(kind, help=help_text).add_subparsers(dest="action", required=True)
        for action, handler in (("list", cmd_list), ("fetch", cmd_fetch)):
            p = actions.add_parser(action, parents=[common, stream, window, crawl],
                                   help=("只列出会处理的报告（不下载），标注 already_saved" if action == "list"
                                         else "抓取并保存为 Markdown"))
            p.set_defaults(handler=handler)
            if kind == "stock":
                p.add_argument("--scope", choices=SCOPES, default="title",
                               help="关键词允许命中的位置，默认 title。abstract（慧搜的「摘要」）召回更宽："
                                    "命中的是站点正文摘录，标题常常没有这个名称，所以标题闸自动失效、"
                                    "由噪音闸兜住晨会/日报/高频数据与未点名的定期跟踪")
                p.add_argument("--keep-noise", action="store_true",
                               help="关掉噪音闸（第四道），保留晨会/日报/数据类与未点名的定期跟踪，用于排查漏抓")
            else:
                p.add_argument("--sub", help="细分行业")
                p.add_argument("--keyword", help="标题关键字过滤")

    status = sub.add_parser("status", parents=[common], help="查询已抓取状态")
    status.add_argument("--folder", help="只看某个分组目录，如 个股_紫金")
    status.add_argument("--failed", action="store_true", help="附带最近的失败记录")
    status.add_argument("--limit", type=int, default=20)
    status.set_defaults(handler=cmd_status)

    pu = sub.add_parser("push", parents=[common, stream], help="把已抓取的分组上传到 WeKnora 知识库")
    pu.add_argument("--kb", required=True, metavar="NAME_OR_ID", help="知识库名称或 ID")
    pu.add_argument("--stock", nargs="+", metavar="NAME", help="推送这些个股的分组（个股_<NAME>）")
    pu.add_argument("--industry", nargs="+", metavar="NAME", help="推送这些行业的分组（行业_<NAME>）")
    pu.add_argument("--create", action="store_true", help="知识库不存在时按名称新建")
    pu.add_argument("--description", help="配合 --create 的新库描述")
    pu.add_argument("--dry-run", action="store_true", help="只列出会上传哪些篇，不上传")
    pu.add_argument("--timeout", type=float, default=600.0, help="等待解析完成的秒数上限（默认 600）")
    pu.set_defaults(handler=cmd_push)

    sub.add_parser("doctor", parents=[common], help="检查 Profile 占用、登录态、是否被限流").set_defaults(handler=cmd_doctor)
    sub.add_parser("industries", parents=[common], help="列出站点上合法的行业与细分行业").set_defaults(handler=cmd_industries)
    sub.add_parser("login", parents=[common], help="打开浏览器手动登录（唯一需要人的步骤）").set_defaults(handler=cmd_login)

    sub.add_parser("spec", parents=[common],
                   help="输出机器可读的接口契约：命令、参数、默认值、退出码、stdout 信封结构").set_defaults(handler=cmd_spec)
    init = sub.add_parser("init", help="写出配置模板（系统级安装后的第一步，不需要已有配置）")
    init.add_argument("--path", metavar="PATH", help="写到哪儿，默认 ~/.hibor/config.yaml")
    init.add_argument("--profile-dir", metavar="PATH",
                      help="配置里写死的 Chrome 目录；默认 <配置目录>/chrome-profile，"
                           "想复用别的登录就把已有 profile 路径填在这里")
    init.add_argument("--force", action="store_true", help="覆盖已存在的配置")
    init.set_defaults(handler=cmd_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # Chinese output on GBK Windows consoles
        except (AttributeError, ValueError):
            pass  # replaced/captured stream without reconfigure support
    args = build_parser().parse_args(argv)
    emit = Emitter(jsonl=getattr(args, "jsonl", False))
    try:
        # `init`/`spec` describe the tool itself, so they must work before any config exists
        settings = None if args.command in CONFIGLESS_COMMANDS else load_config(resolve_config_path(args.config))
        outcome: Outcome = args.handler(args, settings, emit)
    except HiborError as exc:
        # a run aborted mid-way carries what it already saved: non-zero exit still reports the work done
        partial = getattr(exc, "partial", None)
        data = partial.to_dict() if isinstance(partial, FetchResult) else None
        outcome = Outcome(data, {"code": exc.code, "message": str(exc)})
    except Exception as exc:  # unexpected: keep stdout valid JSON, details on stderr
        traceback.print_exc()
        outcome = Outcome(error={"code": "internal", "message": repr(exc)})
    emit.result(outcome.data, outcome.error)
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
