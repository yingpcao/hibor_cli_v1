from datetime import datetime

import pytest

from hibor_cli.models import ConfigError
from hibor_cli.targets import CXZD, INDUSTRY_PREFIX, STOCK_PREFIX, Target, resolve_range

TODAY = datetime(2026, 9, 19, 12, 0)


def stock(**kw) -> Target:
    return Target(kind="stock", name=kw.pop("name", "紫金"), **kw)


def industry(**kw) -> Target:
    return Target(kind="industry", name=kw.pop("name", "有色金属"), **kw)


class TestValidation:
    def test_kind_must_be_one_of_the_two(self):
        with pytest.raises(ConfigError, match="kind"):
            Target(kind="author", name="陈果")

    @pytest.mark.parametrize("name", ["", "   "])
    def test_name_is_required(self, name):
        with pytest.raises(ConfigError, match="目标名称"):
            Target(kind="stock", name=name)

    def test_scope_only_exists_for_stock(self):
        with pytest.raises(ConfigError, match="--scope"):
            industry(scope="abstract")
        with pytest.raises(ConfigError, match="scope"):
            stock(scope="fulltext-body")

    def test_stock_defaults_to_title_scope(self):
        assert stock().scope == "title" and stock().cxzd == CXZD["title"]

    @pytest.mark.parametrize("bad", [0, -3, "many"])
    def test_max_reports_must_be_positive(self, bad):
        with pytest.raises(ConfigError, match="max_reports"):
            stock(max_reports=bad)

    def test_a_bad_range_fails_at_construction_not_mid_run(self):
        with pytest.raises(ConfigError):
            stock(date_range="yesterday")
        with pytest.raises(ConfigError):
            stock(date_range={"end": "2026-09-01"})
        with pytest.raises(ConfigError, match="结束早于开始"):
            stock(date_range={"start": "2026-09-10", "end": "2026-09-01"})
        with pytest.raises(ConfigError, match="YYYY-MM-DD"):
            stock(date_range={"start": "9/1"})


class TestNaming:
    def test_one_folder_per_stock_and_per_industry(self):
        assert stock().folder == f"{STOCK_PREFIX}紫金"
        assert industry().folder == f"{INDUSTRY_PREFIX}有色金属"

    def test_folder_survives_path_hostile_names(self):
        assert stock(name="A/B:C*D?").folder == "个股_A_B_C_D_"

    def test_scope_never_splits_the_folder(self):
        # the same report found under two scopes is one file, not two folders
        assert stock(scope="abstract").folder == stock(scope="title").folder

    def test_label_records_what_the_report_was_collected_for(self):
        assert stock().label == ("stock", "紫金")
        assert industry().label == ("industry", "有色金属")


class TestRanges:
    def test_last_n_days(self):
        start, end = resolve_range("last_7_days", TODAY)
        assert (start, end) == (datetime(2026, 9, 12, 0, 0), TODAY)

    def test_start_only_runs_to_the_end_of_today(self):
        start, end = resolve_range({"start": "2026-09-01"}, TODAY)
        assert start == datetime(2026, 9, 1, 0, 0)
        assert end == datetime(2026, 9, 19, 23, 59, 59, 999999)  # 当天晚上发布的也算进来

    def test_end_is_inclusive_to_the_second(self):
        _, end = resolve_range({"start": "2026-09-01", "end": "2026-09-10"}, TODAY)
        assert end == datetime(2026, 9, 10, 23, 59, 59, 999999)

    def test_window_uses_the_current_clock(self):
        from datetime import timedelta

        start, _ = stock(date_range="last_1_days").window()
        assert start.date() == (datetime.now() - timedelta(days=1)).date()

    @pytest.mark.parametrize("days, expected", [(1, "-3"), (3, "-7"), (7, "1"), (31, "3"),
                                                (92, "6"), (183, "12"), (366, "24"), (400, "24")])
    def test_site_only_accepts_presets_so_we_ask_the_smallest_covering_one(self, days, expected):
        # `sjfw` is a preset list, and the one-day margin means the answer is usually a step wider
        from hibor_cli.search import pick_window

        start, _ = resolve_range(f"last_{days}_days", TODAY)
        assert pick_window(start, TODAY.date()) == expected
