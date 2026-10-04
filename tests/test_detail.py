from hibor_cli.detail import folders_in, report_filename, reports_in, save_markdown
from hibor_cli.models import ReportMeta
from hibor_cli.targets import Target


def meta(n: int = 1, **kw) -> ReportMeta:
    data = dict(id=f"id{n:04d}xxxx", url=f"https://x/{n}", title=f"中信证券-报告{n}",
                published="2026-09-18 10:00:00", org="中信证券", column="公司研究", authors="张三",
                rating="买入", pages="31", subject="601899(紫金矿业)")
    data.update(kw)
    return ReportMeta(**data)


def read(path):
    return path.read_text(encoding="utf-8")


class TestSave:
    def test_file_lands_in_the_target_folder_named_by_its_own_title(self, tmp_path):
        target = Target(kind="stock", name="紫金")
        path = save_markdown(meta(), target.folder, "正文。\n", tmp_path / "out", target.label, "company")
        assert path.parent == tmp_path / "out" / "个股_紫金"
        assert path.name == "报告1_中信证券.md"

    def test_frontmatter_records_why_the_report_was_kept(self, tmp_path):
        target = Target(kind="stock", name="紫金")
        text = read(save_markdown(meta(), target.folder, "正文。\n", tmp_path / "out", target.label, "company"))
        head = text.split("---")[1]
        assert 'title: "中信证券-报告1"' in head
        assert "stock: 紫金" in head
        assert 'subject: "601899(紫金矿业)"' in head
        assert "relevance: company" in head
        assert "org: 中信证券" in head and "published: 2026-09-18 10:00:00" in head
        assert "source: https://x/1" in head
        assert text.endswith("正文。\n")

    def test_industry_reports_are_labelled_by_industry_and_have_no_subject(self, tmp_path):
        target = Target(kind="industry", name="有色金属")
        path = save_markdown(meta(subject=""), target.folder, "正文。\n", tmp_path / "out", target.label)
        head = read(path).split("---")[1]
        assert "industry: 有色金属" in head and "relevance:" not in head and "subject:" not in head

    def test_quotes_in_titles_cannot_break_the_frontmatter(self, tmp_path):
        target = Target(kind="stock", name="紫金")
        path = save_markdown(meta(title='他说"涨"了'), target.folder, "正文。\n", tmp_path / "out", target.label)
        assert "'涨'" in read(path)

    def test_rerunning_the_same_report_overwrites_one_file(self, tmp_path):
        target = Target(kind="industry", name="有色")
        first = save_markdown(meta(), target.folder, "旧\n", tmp_path / "out", target.label)
        second = save_markdown(meta(), target.folder, "新\n", tmp_path / "out", target.label)
        assert first == second and read(second) == read(first) and "新" in read(second)

    def test_a_different_report_with_the_same_title_keeps_both_files(self, tmp_path):
        target = Target(kind="industry", name="有色")
        first = save_markdown(meta(), target.folder, "旧\n", tmp_path / "out", target.label)
        # 券商复用同一标题的另一次点评：id 不同，所以文件名必须不同，否则后一篇静默覆盖前一篇
        twin = meta(2, title=meta().title)
        second = save_markdown(twin, target.folder, "新\n", tmp_path / "out", target.label)
        assert first.name == "报告1_中信证券.md"
        assert second.name == "报告1_中信证券_id0002xx.md"
        assert first.exists() and read(second).endswith("新\n")


class TestFilename:
    def test_the_leading_broker_segment_moves_to_the_end(self):
        m = meta(title="东吴证券-紫金龙净-600388-海外矿山光储项目加速落地-260927", org="东吴证券")
        assert report_filename(m) == "紫金龙净-600388-海外矿山光储项目加速落地-260927_东吴证券.md"

    def test_a_title_that_does_not_start_with_the_broker_is_kept_as_is(self):
        m = meta(title="2026年铜供需展望", org="中金公司")
        assert report_filename(m) == "2026年铜供需展望_中金公司.md"

    def test_a_broker_only_title_does_not_become_an_empty_name(self):
        assert report_filename(meta(title="中信证券", org="中信证券")) == "中信证券_中信证券.md"

    def test_the_date_and_report_id_are_gone_but_the_report_day_stays(self):
        # 研报日期是慧博标题自带的一段（-260927），published 的分享时间则只在 frontmatter 里
        name = report_filename(meta(title="太平洋证券-紫金黄金国际-2259.HK-业绩高增-260919",
                                    org="太平洋证券"))
        assert name == "紫金黄金国际-2259.HK-业绩高增-260919_太平洋证券.md"
        assert "2026-09-18" not in name and "id0001" not in name

    def test_windows_hostile_characters_become_underscores(self):
        m = meta(title='中信证券-测算:A/B 的"C|D"', org="中信证券")
        assert report_filename(m) == "测算_A_B 的_C_D__中信证券.md"

    def test_the_title_is_bounded_and_the_broker_segment_is_shorter(self):
        org = "中信证券股份有限公司上海分公司额外很长的一段机构名"  # 25 chars, cut to 24
        m = meta(title="长" * 200, org=org)
        name = report_filename(m)
        assert name == "长" * 80 + "_中信证券股份有限公司上海分公司额外很长的一段机构.md"


class TestLayout:
    def test_folders_are_what_exists_on_disk(self, tmp_path):
        (tmp_path / "个股_紫金").mkdir()
        (tmp_path / "行业_有色").mkdir()
        (tmp_path / ".scratch").mkdir()
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        assert folders_in(tmp_path) == ["个股_紫金", "行业_有色"]

    def test_missing_output_dir_is_empty_not_an_error(self, tmp_path):
        assert folders_in(tmp_path / "nope") == []

    def test_push_inventory_skips_the_folder_readme_but_keeps_subfolders(self, tmp_path):
        (tmp_path / "b.md").write_text("x", encoding="utf-8")
        (tmp_path / "a.md").write_text("x", encoding="utf-8")
        (tmp_path / "README.md").write_text("x", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.md").write_text("x", encoding="utf-8")
        (tmp_path / "清单.csv").write_text("x", encoding="utf-8")
        assert [f.name for f in reports_in(tmp_path)] == ["a.md", "b.md", "c.md"]
