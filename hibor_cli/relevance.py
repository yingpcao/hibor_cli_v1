"""个股检索的相关性判决：滤掉慧搜的分词误命中，再滤掉顺带提到本股的例行壳子。

慧搜是分词模糊匹配，搜“紫金”会连“华鑫期货…有色金属…”一起返回，所以判四道：

  1. 标题闸（列表期）—— `--scope title` 时命中点就在标题，标题里必须真的连着出现该名称。
     `abstract`/`fulltext` 的命中点在摘要或全文里，标题本来就可能没有这个名称，所以不在这里判。
  2. 公司/行业二分（列表期）—— subject 是 `601899(紫金矿业)` 者为 company，`(锡行业)` 或空者为
     industry。company 恒留：站点已经点名了这只股票。
  3. 噪音闸（列表期）—— 晨会/日报/高频数据这类壳子，以及标题没点名本股的定期跟踪与点评，都丢掉。
     只有 industry 类会走到这里，所以 company 的《半年报点评》不受影响。
  4. 正文闸（详情期）—— industry 的正文里必须提到该名称，否则丢弃。

没有股票代码可用（本项目不调站点联想接口），名称就是唯一的匹配串，所以填简称（“紫金”）比填全称
（“紫金矿业”）召回更宽。第 4 道看的是 `.abstruct-info` 摘录而非整份 PDF，摘录里没写到的相关报告会
被误杀 —— 这是精度换召回，宁可漏也不要往知识库里灌误命中。`--scope abstract/fulltext` 时命中点本身
就在摘录里，所以第 4 道几乎不会触发；它是留给“列表页命中在正文、详情页摘录却没复述那句”的兜底。
"""
import re

from .models import ReportMeta
from .targets import Target

COMPANY, INDUSTRY, DROP = "company", "industry", "drop"
# `601899(紫金矿业)` -> 代码 + 名称；`2259.HK(紫金黄金国际)` 是港股代码；`(锡行业)` -> 只有名称，不算 company
SUBJECT_RE = re.compile(r"^(?P<code>[0-9A-Za-z]{2,8}(?:\.[0-9A-Za-z]{1,3})?)?\((?P<name>[^()]+)\)$")

# 站点给的栏目是面包屑（`行业分析→定期研报→行业周报`、`晨会早刊→晨会纪要`），按段精确匹配。
_SEGMENTS = re.compile(r"[→>|/]")
# 壳子栏目：晨会/早间资讯是别人研究的目录，行业数据/高频数据是 Excel 底稿，定期日报周报是流水账。
# 它们不是“冲着这家公司写的一篇研究”，标题点了名也不留。
SHELL_SEGMENTS = ("晨会早刊", "晨会纪要", "早间资讯", "行业数据", "数据周报", "高频数据",
                  "期货日报", "期货周报")
SHELL_TITLE = re.compile(
    r"晨会|早会|晨报|早报|早参|晚报|夜报|日报|盘前|盘后|高频数据|数据周报|数据跟踪|每日数据|数据库|"
    r"数据汇总|一览表|明细表|周度观点|excel|xls|每日[\u4e00-\u9fa5]{0,6}(?:导航|纵览|晨报|提醒|速递|跟踪|综述)",
    re.IGNORECASE)
# 定期跟踪与点评：慧博把它归在 `定期研报`/`定期策略` 下，摘要模式命中到它们基本是“本期覆盖名单里
# 顺手列了这只”。标题连着出现名称的（《环保行业跟踪周报：紫金龙净海外矿山…》）是冲着它写的，留。
PERIODIC_SEGMENTS = ("定期研报", "定期策略")
# 只看叶子段：`行业点评`/`事件点评`/`半年报点评` 是点评，而父级 `行业评论`/`公司评论` 下面还挂着
# 专题报告与调研，不能一并当成点评。
COMMENT_LEAF = ("点评", "简评", "快评")
COMMENT_TITLE = re.compile("|".join(COMMENT_LEAF))


def _segments(column: str) -> list[str]:
    return [s.strip() for s in _SEGMENTS.split(column) if s.strip()]


def noise_reason(meta: ReportMeta, target: Target) -> str:
    """列表期噪音判决 -> 丢弃原因，""表示保留。只对 industry 类调用（company 恒留）。"""
    segments = _segments(meta.column)
    hard = next((s for s in segments if s in SHELL_SEGMENTS), "")
    if hard:
        return f"例行汇编/数据类栏目「{hard}」，不是针对本股的研究"
    shell = SHELL_TITLE.search(meta.title)
    if shell:
        return f"例行汇编/数据类标题「{shell.group(0)}」，不是针对本股的研究"
    if target.name in meta.title:
        return ""  # 标题连着出现本股：这篇是冲着它写的
    periodic = next((s for s in segments if s in PERIODIC_SEGMENTS), "")
    if periodic:
        return f"定期跟踪类栏目「{periodic}」，标题未出现「{target.name}」（只在正文提及）"
    comment_seg = next((s for s in segments if s.endswith(COMMENT_LEAF)), "")
    if comment_seg:
        return f"点评类栏目「{comment_seg}」，标题未出现「{target.name}」（只在正文提及）"
    title_comment = COMMENT_TITLE.search(meta.title)
    if title_comment:
        return f"点评类标题「{title_comment.group(0)}」，标题未出现「{target.name}」（只在正文提及）"
    return ""


def is_company(subject: str, stock: str) -> bool:
    m = SUBJECT_RE.match(subject.strip())
    if not m:
        return False
    code, name = (m.group("code") or "").upper(), m.group("name")
    if code and stock.upper() == code:
        return True  # 按代码搜索时，subject 里的代码就是最硬的证据
    if not code:
        return False  # 没有代码的一律不算：行业 subject 里也常含品种名
    return stock in name or name in stock


def list_verdict(meta: ReportMeta, target: Target) -> tuple[str, str]:
    """列表期判决 -> (company | industry | drop, 丢弃原因)。行业任务返回 ("", "")，即不干预。"""
    if target.kind != "stock":
        return "", ""
    if is_company(meta.subject, target.name):
        return COMPANY, ""
    if target.scope == "title" and target.name not in meta.title:
        return DROP, f"标题未连着出现「{target.name}」（分词误命中）"
    if not target.keep_noise:
        reason = noise_reason(meta, target)
        if reason:
            return DROP, reason
    return INDUSTRY, ""


def body_verdict(body_md: str, target: Target, verdict: str) -> tuple[bool, str]:
    """详情期判决 -> (是否保留, 丢弃原因)。company 与行业任务恒留。"""
    if verdict != INDUSTRY or target.name in body_md:
        return True, ""
    return False, f"正文未提及「{target.name}」"
