import pytest

from hibor_cli.models import ReportMeta
from hibor_cli.relevance import (COMPANY, DROP, INDUSTRY, body_verdict, is_company, list_verdict,
                                noise_reason)
from hibor_cli.targets import Target


def meta(title: str, subject: str = "", column: str = "") -> ReportMeta:
    return ReportMeta(id="id1xxxxxx", url="https://x/1", title=title, published="2026-09-18",
                      org="o", column=column, authors="", rating="", pages="", subject=subject)


def stock(scope: str = "title", **kw) -> Target:
    return Target(kind="stock", name="紫金", scope=scope, **kw)


class TestIsCompany:
    @pytest.mark.parametrize("subject, stock_name, expected", [
        ("601899(紫金矿业)", "紫金", True),   # 站点点明了这只股票
        ("601899(中金黄金)", "紫金", False),  # 有代码，但不是这家
        ("(锡行业)", "锡", False),            # 没有代码的行业 subject：常含品种名，不能算
        ("2259.HK(紫金黄金国际)", "紫金黄金国际", True),  # 港股代码带点，也是代码
        ("", "紫金", False),
        ("紫金矿业", "紫金", False),          # 连括号结构都没有
    ])
    def test_subject_syntax_is_the_evidence(self, subject, stock_name, expected):
        assert is_company(subject, stock_name) is expected

    def test_code_search_matches_the_code_column(self):
        assert is_company("601899(紫金矿业)", "601899") is True
        assert is_company("601899(紫金矿业)", "6018") is False  # 代码要整段对上

    def test_a_name_without_a_code_never_counts_even_when_it_matches(self):
        assert is_company("(紫金行业)", "紫金") is False


class TestListVerdict:
    def test_industry_targets_are_never_judged(self):
        assert list_verdict(meta("有色周报"), Target(kind="industry", name="有色金属")) == ("", "")

    def test_company_wins_before_the_title_gate(self):
        # 标题里没有“紫金”也没关系：subject 已经点名
        assert list_verdict(meta("中信证券-铜价周报", "601899(紫金矿业)"), stock()) == (COMPANY, "")

    def test_title_scope_drops_tokenised_false_positives(self):
        verdict, reason = list_verdict(meta("华鑫期货-锡业有色周报"), stock())
        assert verdict == DROP and "分词误命中" in reason

    def test_wide_scopes_cannot_be_judged_from_the_title(self):
        # 命中点在摘要/全文里，标题本来就可能没有这个名称
        assert list_verdict(meta("有色周报"), stock(scope="abstract")) == (INDUSTRY, "")
        assert list_verdict(meta("有色周报"), stock(scope="fulltext")) == (INDUSTRY, "")


class TestBodyVerdict:
    def test_industry_reports_must_mention_the_stock(self):
        keep, reason = body_verdict("本期只谈锌价。", stock(), INDUSTRY)
        assert (keep, reason) == (False, "正文未提及「紫金」")

    def test_a_body_that_names_the_stock_is_kept(self):
        assert body_verdict("紫金矿业扩产。", stock(), INDUSTRY) == (True, "")

    @pytest.mark.parametrize("verdict", [COMPANY, ""])
    def test_company_and_industry_targets_skip_the_gate(self, verdict):
        assert body_verdict("只谈锌价。", stock(), verdict) == (True, "")

    def test_wide_scopes_keep_the_gate_as_a_backstop(self):
        # 摘要命中时正文闸几乎不会触发，但“列表命中在正文、详情摘录没复述”仍会被拦下
        assert body_verdict("只谈锌价。", stock(scope="abstract"), INDUSTRY)[0] is False


# 以下标题/栏目照 2026-10-04 慧搜 `--scope abstract` 的真实结果，不另造样例
class TestNoiseGate:
    """第四道：摘要模式里那些只“顺带提到”本股的晨会、日报、数据类和定期跟踪。"""

    @pytest.mark.parametrize("column,title", [
        ("晨会早刊→晨会纪要", "光大证券-晨会速递-260914"),
        ("港美研究→港股→晨会早刊", "越秀证券-每日晨报-260925"),
        ("期货研究→期货日报", "宁证期货-期现日报-260929"),
        ("行业分析→行业数据→数据周报", "光大证券-有色金属行业金属新材料高频数据周报-260928"),
        ("港美研究→港股→投资策略", "国都证券（香港）-每日港股导航-260929"),
    ])
    def test_routine_shells_go_even_when_the_title_names_the_stock(self, column, title):
        assert noise_reason(meta(f"紫金矿业{title}", column=column), stock(scope="abstract"))

    def test_the_morning_note_is_dropped_at_the_column(self):
        verdict, reason = list_verdict(meta("光大证券-晨会速递-260914",
                                            column="晨会早刊→晨会纪要"), stock(scope="abstract"))
        assert verdict == DROP and "晨会早刊" in reason  # 原因是命中的那一段栏目

    def test_periodic_tracking_without_the_stock_in_the_title_is_noise(self):
        item = meta("东吴证券-公用事业行业跟踪周报：五部门组织绿色算力设施推荐-260928",
                    column="行业分析→定期研报→行业周报")
        verdict, reason = list_verdict(item, stock(scope="abstract"))
        assert verdict == DROP and "定期跟踪" in reason and "正文提及" in reason

    def test_periodic_tracking_that_headlines_the_stock_survives(self):
        item = meta("东吴证券-环保行业跟踪周报：紫金龙净海外矿山光储项目加速落地-260928",
                    column="行业分析→定期研报→行业周报")
        assert list_verdict(item, stock(scope="abstract")) == (INDUSTRY, "")

    def test_an_industry_comment_that_only_mentions_the_stock_is_noise(self):
        item = meta("华龙证券-有色金属行业点评报告：年内再加息预期升温-260923",
                    column="行业分析→行业评论→行业点评")
        verdict, reason = list_verdict(item, stock(scope="abstract"))
        assert verdict == DROP and "行业点评" in reason

    def test_a_comment_in_the_title_counts_even_without_a_column(self):
        # 有些条目站点没给栏目，只能看标题里的「点评」
        item = meta("某某机构-钢铁行业下半年展望点评", column="")
        verdict, reason = list_verdict(item, stock(scope="abstract"))
        assert verdict == DROP and "点评类标题" in reason

    def test_a_parent_comment_column_is_not_itself_a_comment(self):
        # `行业评论` 下还挂着专题报告与调研：只有叶子段带点评才算点评
        item = meta("国金证券-有色金属行业：全球主流铜企Q2更新-260904",
                    column="行业分析→行业评论→专题报告")
        assert list_verdict(item, stock(scope="abstract")) == (INDUSTRY, "")

    def test_the_gate_never_touches_a_report_the_site_named(self):
        # 站点已点名 002555(三七互娱)：《半年报点评》是这家公司自己的研究，不是壳子
        target = Target(kind="stock", name="三七互娱", scope="abstract")
        item = meta("东吴证券-三七互娱-002555-2026年半年报点评-260828",
                    subject="002555(三七互娱)", column="公司调研→财报点评→半年报点评")
        assert list_verdict(item, target) == (COMPANY, "")

    def test_title_scope_is_not_newly_filtered(self):
        # 标题点了名的定期周报，在 title 模式下和以前一样留下
        item = meta("紫金矿业周度跟踪：产量环比提升", column="行业分析→定期研报→行业周报")
        assert list_verdict(item, stock()) == (INDUSTRY, "")

    def test_a_daily_strategy_note_is_a_shell_whatever_column_it_sits_in(self):
        # 站点把《招财日报》归在 `投资策略` 下，所以只能靠标题认出它是每日一份的壳子
        item = meta("招银国际-招财日报：每日投资策略-260909", column="港美研究→港股→投资策略")
        verdict, reason = list_verdict(item, stock(scope="abstract"))
        assert verdict == DROP and "日报" in reason

    def test_keep_noise_bypasses_the_gate_for_triage(self):
        item = meta("光大证券-晨会速递-260914", column="晨会早刊→晨会纪要")
        assert list_verdict(item, stock(scope="abstract", keep_noise=True)) == (INDUSTRY, "")

    def test_an_unknown_column_with_a_bare_title_is_left_to_the_body_gate(self):
        item = meta("某某机构-紫金矿业产业链调研", column="")
        assert list_verdict(item, stock(scope="abstract")) == (INDUSTRY, "")
