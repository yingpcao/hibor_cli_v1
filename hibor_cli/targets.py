"""What to crawl: two target kinds and the date range they run over.

`stock` searches 慧搜 for a stock name, `industry` walks the 行业 report list. Everything else the
older hibor-web crawler could search (author, ratings, mixed scopes, free-form 慧搜 keywords) is
deliberately absent: an agent should not have to choose between six scopes to answer
"最近这家公司的研报".
"""
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .models import ConfigError

KINDS = ("stock", "industry")
# 慧搜 "内容" dropdown: what the keyword may match. `title` is the default because it is the only
# scope whose match site the 标题闸 can check; under `abstract`/`fulltext` the noise gate takes over
# on the list page (栏目 + 标题) and the body gate backstops it.
SCOPES = ("title", "abstract", "fulltext")
CXZD = {"title": "bt", "abstract": "zy", "fulltext": "qw"}
DEFAULT_SCOPE = "title"
DEFAULT_DAYS = 7
DEFAULT_MAX = 100
DEFAULT_RANGE = f"last_{DEFAULT_DAYS}_days"
STOCK_PREFIX, INDUSTRY_PREFIX = "个股_", "行业_"
_LAST_N = re.compile(r"last_(\d+)_days?")
_BAD_PATH_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ConfigError(f"日期格式应为 YYYY-MM-DD: {value!r}") from exc


def resolve_range(spec: Any, now: datetime) -> tuple[datetime, datetime]:
    """`last_N_days` or {start, end?} -> inclusive (start 00:00, end) datetimes."""
    if isinstance(spec, Mapping):
        if "start" not in spec:
            raise ConfigError(f"date_range 需要 start: {dict(spec)}")
        start = datetime.combine(_to_date(spec["start"]), datetime.min.time())
        end = datetime.combine(_to_date(spec.get("end", now.date())), datetime.max.time())
        if end < start:
            raise ConfigError(f"date_range 结束早于开始: {start:%F} > {end:%F}")
        return start, end
    match = _LAST_N.fullmatch(str(spec))
    if not match:
        raise ConfigError(f"date_range 格式错误（应为 last_N_days 或 start/end）: {spec!r}")
    day = (now - timedelta(days=int(match[1]))).date()
    return datetime.combine(day, datetime.min.time()), now


@dataclass(frozen=True)
class Target:
    kind: str
    name: str  # stock: 个股简称/代码; industry: 一级行业名（见 `hibor industries`）
    date_range: Any = DEFAULT_RANGE
    max_reports: int = DEFAULT_MAX
    scope: str = DEFAULT_SCOPE  # stock only: 关键词命中的位置
    keep_noise: bool = False  # stock only: 关掉噪音闸（第四道），用来排查“是不是被误滤了”
    sub_industry: str = ""  # industry only
    title_keyword: str = ""  # industry only: 站点标题过滤框

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ConfigError(f"kind 必须是 {KINDS} 之一: {self.kind!r}")
        if not self.name.strip():
            raise ConfigError("缺少目标名称（个股名或行业名）")
        if self.kind == "industry" and self.scope != DEFAULT_SCOPE:
            raise ConfigError("行业抓取走行业列表页，没有 --scope 概念")
        if self.kind == "stock" and self.scope not in SCOPES:
            raise ConfigError(f"scope 必须是 {SCOPES} 之一: {self.scope!r}")
        if not isinstance(self.max_reports, int) or self.max_reports < 1:
            raise ConfigError(f"max_reports 必须是正整数: {self.max_reports!r}")
        resolve_range(self.date_range, datetime.now())  # fail fast on a bad range

    @property
    def folder(self) -> str:
        """Output folder and dedupe scope: one folder per stock / per industry, whatever the scope,
        so the same report found under two scopes is one file rather than two."""
        return _BAD_PATH_CHARS.sub("_", f"{STOCK_PREFIX if self.kind == 'stock' else INDUSTRY_PREFIX}{self.name}")

    @property
    def label(self) -> tuple[str, str]:
        """Frontmatter (key, value) recording what the report was collected for."""
        return (self.kind, self.name)

    @property
    def cxzd(self) -> str:
        return CXZD[self.scope]

    def window(self) -> tuple[datetime, datetime]:
        return resolve_range(self.date_range, datetime.now())
