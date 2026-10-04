"""Parsers exercised against captured site HTML: these fixtures are the only place the real
column positions and ids of 慧搜 / 行业页 are recorded."""
import pytest

from hibor_cli.detail import _safe, to_markdown
from hibor_cli.industry import parse_industries, parse_list
from hibor_cli.models import BlockedError
from hibor_cli.search import parse_results


class TestSearchResults:
    def test_total_and_page_size(self, fixture_text):
        total, items = parse_results(fixture_text("search_sa.html"))
        assert (total, len(items)) == (365, 10)

    def test_columns_are_positional_on_the_first_row(self, fixture_text):
        _, items = parse_results(fixture_text("search_sa.html"))
        first = items[0]
        assert (first.id, first.published, first.org) == \
               ("ea495deb200f895f7123712a90d89c49", "2026-09-19", "落基山研究所")
        assert first.column == "行业分析→行业评论→行业调研"
        assert first.pages == "共59页"
        assert first.url == "https://www.hibor.com.cn/data/ea495deb200f895f7123712a90d89c49.html"

    def test_subject_is_the_second_column_and_says_who_the_report_is_about(self, fixture_text):
        _, items = parse_results(fixture_text("search_sa.html"))
        assert items[0].subject == "(钢铁供应链行业)"
        assert items[1].subject == ""  # 该行为空时留空，个股判决据此判不出 company

    def test_missing_total_marker_means_the_session_is_broken(self):
        with pytest.raises(BlockedError, match="hidTotal"):
            parse_results("<html><body>被风控了</body></html>")

    def test_a_page_without_items_is_not_an_error(self):
        assert parse_results('<input id="hidTotal" value="0">') == (0, [])


class TestIndustryList:
    def test_every_field_comes_from_its_label(self, fixture_text):
        items = parse_list(fixture_text("industry_list.html"))
        assert [i.id[:8] for i in items] == ["607d8c7f", "0cb12e88"]
        assert items[0].published == "2026-09-19 09:21:11"  # 行业页给到秒，慧搜只给到日
        assert (items[0].org, items[0].rating, items[0].pages) == ("广发证券", "买入", "31 页")
        assert items[0].subject == ""  # 这一列只存在于慧搜

    def test_empty_page(self):
        assert parse_list("<html><body></body></html>") == []

    def test_industries_and_their_sub_industries(self, fixture_text):
        assert parse_industries(fixture_text("industry_list.html")) == [
            {"name": "电子", "sub_industries": ["半导体", "元件"]},
            {"name": "有色金属", "sub_industries": ["金属新材料", "工业金属"]},
        ]

    def test_no_hang_ye_blob_means_no_sub_industries(self):
        assert parse_industries('<select id="f1_hy1"><option value="电子">电子</option><option value="all">全部</option></select>') == [
            {"name": "电子", "sub_industries": []}]


class TestMarkdown:
    def test_watermark_and_empty_links_are_stripped(self):
        html = ('<p>正文开头</p><p>　缩进段落</p>'
                '<a href="https://www.hibor.com.cn（慧博投研资讯）">https://www.hibor.com.cn（慧博投研资讯）</a>')
        md = to_markdown(html)
        assert md.startswith("正文开头") and "\n缩进段落" in md
        assert "慧博投研资讯" not in md and "](" not in md
        assert md.endswith("\n") and "\n\n\n" not in md

    def test_headings_become_atx(self):
        assert to_markdown("<h2>要点</h2>") == "## 要点\n"

    @pytest.mark.parametrize("name, expected", [
        ("a/b:c*d", "a_b_c_d"), ("带换行\n标题", "带换行_标题"), ("尾部空格  ", "尾部空格"),
    ])
    def test_filenames_survive_windows(self, name, expected):
        assert _safe(name) == expected

    def test_long_titles_are_cut_before_the_extension(self):
        assert len(_safe("很长" * 60)) == 80
