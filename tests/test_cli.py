import json
from contextlib import nullcontext
from pathlib import Path

import pytest

from hibor_cli import __version__, cli
from hibor_cli import config as config_mod
from hibor_cli.config import load_config
from hibor_cli.crawl import FetchResult
from hibor_cli.models import BlockedError, ConfigError, LoginRequiredError, ProfileBusyError
from hibor_cli.session import Session
from tests.fakes import FakePage


def call(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr().out.strip()
    if "--jsonl" in argv:  # event stream: the envelope is the last line
        return code, json.loads(out.splitlines()[-1])
    return code, json.loads(out)  # default mode: the whole stdout is one JSON document


def fake_session(page):
    return lambda _profile=None, _headless=False: nullcontext(Session(ctx=None, list_page=page, detail_page=None))


class TestParser:
    def test_stock_defaults(self):
        args = cli.build_parser().parse_args(["stock", "fetch", "紫金"])
        target = cli._target(args)
        assert (target.kind, target.name, target.scope, target.max_reports, target.date_range) == \
               ("stock", "紫金", "title", 100, "last_7_days")
        assert target.keep_noise is False  # 噪音闸默认开着

    def test_keep_noise_reaches_the_target(self):
        args = cli.build_parser().parse_args(["stock", "list", "紫金", "--scope", "abstract", "--keep-noise"])
        assert (cli._target(args).scope, cli._target(args).keep_noise) == ("abstract", True)

    def test_keep_noise_is_not_offered_for_industry(self):
        with pytest.raises(SystemExit) as exc:
            cli.build_parser().parse_args(["industry", "fetch", "有色金属", "--keep-noise"])
        assert exc.value.code == 2

    def test_industry_carries_sub_industry_and_title_keyword(self):
        args = cli.build_parser().parse_args(
            ["industry", "list", "有色金属", "--sub", "工业金属", "--keyword", "周报"])
        target = cli._target(args)
        assert (target.sub_industry, target.title_keyword, target.folder) == ("工业金属", "周报", "行业_有色金属")

    def test_explicit_dates_beat_days(self):
        args = cli.build_parser().parse_args(
            ["stock", "list", "紫金", "--from", "2026-09-01", "--to", "2026-09-19", "--days", "3"])
        assert cli._target(args).date_range == {"start": "2026-09-01", "end": "2026-09-19"}

    def test_days_only(self):
        args = cli.build_parser().parse_args(["industry", "fetch", "电子", "--days", "3"])
        assert cli._target(args).date_range == "last_3_days"

    def test_bad_scope_is_a_usage_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["stock", "fetch", "x", "--scope", "body"])
        assert exc.value.code == 2

    def test_scope_is_not_offered_for_industry(self):
        with pytest.raises(SystemExit) as exc:
            cli.build_parser().parse_args(["industry", "fetch", "有色金属", "--scope", "abstract"])
        assert exc.value.code == 2

    def test_sub_is_not_offered_for_stock(self):
        with pytest.raises(SystemExit) as exc:
            cli.build_parser().parse_args(["stock", "fetch", "紫金", "--sub", "工业金属"])
        assert exc.value.code == 2

    def test_a_target_needs_list_or_fetch(self):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["stock"])


class TestConfig:
    def test_loads_paths_relative_to_the_config(self, config_path, tmp_path):
        settings = load_config(Path(config_path))
        assert settings.output_dir == tmp_path / "out"
        assert settings.db_path == tmp_path / "state" / "reports.db"
        assert settings.profile_dir == tmp_path / "profile"
        assert settings.delay.batch_size == 5

    def test_missing_config_is_a_config_error(self, capsys, tmp_path):
        code, env = call(capsys, "status", "--config", str(tmp_path / "x.yaml"))
        assert code == 2 and env["error"]["code"] == "config_error"

    def test_a_jobs_section_is_rejected_so_the_old_config_cannot_load_silently(self, capsys, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("jobs:\n  - {name: a, kind: industry, industry: 有色金属}\n", encoding="utf-8")
        code, env = call(capsys, "status", "--config", str(path))
        assert code == 2 and "未知字段" in env["error"]["message"]


class TestCrawlCommands:
    def test_fetch_maps_result_to_exit_code(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "fetch_target", lambda *a, **k: FetchResult("个股_紫金", 3, 1, 0, 0))
        code, env = call(capsys, "stock", "fetch", "紫金", "--config", config_path)
        assert code == 0 and env["ok"] is True and env["data"]["saved"] == 3

    def test_failed_reports_are_a_partial_failure(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "fetch_target", lambda *a, **k: FetchResult("个股_紫金", 3, 0, 0, 2))
        code, env = call(capsys, "stock", "fetch", "紫金", "--config", config_path)
        assert code == 5 and env["error"]["code"] == "partial_failure"
        assert env["data"]["saved"] == 3  # data is always present, even on errors

    @pytest.mark.parametrize("exc, expected_code", [(BlockedError("风控"), 4), (LoginRequiredError("登录失效"), 3)])
    def test_aborted_run_still_carries_saved_data(self, monkeypatch, capsys, config_path, exc, expected_code):
        def abort(*a, **k):
            exc.partial = FetchResult("行业_有色", 4, 0, 0, 3, saved_paths=("p1.md",) * 4)
            raise exc

        monkeypatch.setattr(cli, "fetch_target", abort)
        code, env = call(capsys, "industry", "fetch", "有色", "--config", config_path)
        assert code == expected_code and env["ok"] is False and env["error"]["code"] == exc.code
        assert (env["data"]["saved"], env["data"]["failed"]) == (4, 3)
        assert len(env["data"]["saved_paths"]) == 4

    def test_profile_busy_exits_6(self, monkeypatch, capsys, config_path):
        def busy(*a, **k):
            raise ProfileBusyError("in use")

        monkeypatch.setattr(cli, "fetch_target", busy)
        code, env = call(capsys, "stock", "fetch", "紫金", "--config", config_path)
        assert code == 6 and env["error"]["code"] == "profile_busy"

    def test_unexpected_error_keeps_stdout_valid_json(self, monkeypatch, capsys, config_path):
        def crash(*a, **k):
            raise RuntimeError("bug")

        monkeypatch.setattr(cli, "fetch_target", crash)
        code, env = call(capsys, "stock", "fetch", "紫金", "--config", config_path)
        assert code == 1 and env["error"]["code"] == "internal"

    def test_list_reports_what_would_be_fetched(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "list_target", lambda *a, **k: [
            {"id": "a", "already_saved": False}, {"id": "b", "already_saved": True}])
        code, env = call(capsys, "stock", "list", "紫金", "--config", config_path)
        assert code == 0 and (env["data"]["folder"], env["data"]["count"], env["data"]["new"]) == ("个股_紫金", 2, 1)

    def test_jsonl_mode_ends_with_the_result_event(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "fetch_target", lambda *a, **k: FetchResult("g", 1, 0, 0, 0))
        code, last = call(capsys, "stock", "fetch", "紫金", "--jsonl", "--config", config_path)
        assert code == 0 and last["event"] == "result" and last["ok"] is True

    def test_stdout_is_json_only(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "fetch_target", lambda *a, **k: FetchResult("g", 1, 0, 0, 0))
        cli.main(["stock", "fetch", "紫金", "--config", config_path])
        captured = capsys.readouterr()
        json.loads(captured.out)
        assert captured.out.strip().startswith("{")

    def test_an_impossible_target_is_a_config_error(self, capsys, config_path):
        code, env = call(capsys, "stock", "fetch", "", "--config", config_path)
        assert code == 2 and env["error"]["code"] == "config_error"


class TestStatus:
    def test_empty_db(self, capsys, config_path):
        code, env = call(capsys, "status", "--config", config_path, "--failed")
        # status names the config it used: the same command in another cwd can mean another workspace
        assert code == 0 and env["data"] == {
            "config_path": str(Path(config_path).resolve()), "folders": [], "failed": []}

    def test_counts_come_from_the_state_db(self, capsys, config_path, tmp_path):
        from hibor_cli.models import ReportMeta
        from hibor_cli.store import Store

        store = Store(load_config(Path(config_path)).db_path)
        store.mark(ReportMeta("a", "u", "标题", "2026-09-18", "o", "", "", "", ""), "个股_紫金", "done")
        store.close()
        code, env = call(capsys, "status", "--folder", "个股_紫金", "--config", config_path)
        assert code == 0 and env["data"]["folders"] == [
            {"folder": "个股_紫金", "done": 1, "empty": 0, "failed": 0, "filtered": 0}]


class TestPush:
    def test_credentials_come_from_config(self, monkeypatch, capsys, config_path, tmp_path, fake_weknora):
        seen = {}
        monkeypatch.setattr(cli.weknora, "make_client", lambda cfg, **kw: seen.update(cfg.__dict__) or object())
        (tmp_path / "out" / "个股_紫金").mkdir(parents=True)
        code, env = call(capsys, "push", "--kb", "RP-小金属", "--stock", "紫金", "--config", config_path)
        assert code == 0 and env["ok"] is True
        assert seen == {"base_url": "http://weknora.test/api/v1", "api_key": "sk-test"}
        assert env["data"]["kb"] == {"id": "kb-1", "name": "RP-小金属"}
        assert fake_weknora == [("个股_紫金", False)]

    def test_industry_and_stock_flags_pick_their_folders(self, capsys, config_path, tmp_path, fake_weknora):
        (tmp_path / "out" / "个股_紫金").mkdir(parents=True)
        (tmp_path / "out" / "行业_有色").mkdir(parents=True)
        (tmp_path / "out" / "行业_电子").mkdir(parents=True)
        code, env = call(capsys, "push", "--kb", "库", "--stock", "紫金", "--industry", "有色", "电子",
                         "--config", config_path)
        assert code == 0 and [f["folder"] for f in env["data"]["folders"]] == ["个股_紫金", "行业_有色", "行业_电子"]

    def test_without_targets_every_saved_folder_is_pushed(self, capsys, config_path, tmp_path, fake_weknora):
        (tmp_path / "out" / "个股_紫金").mkdir(parents=True)
        (tmp_path / "out" / "行业_有色").mkdir(parents=True)
        code, env = call(capsys, "push", "--kb", "库", "--config", config_path)
        assert code == 0 and [f["folder"] for f in env["data"]["folders"]] == ["个股_紫金", "行业_有色"]

    def test_dry_run_passes_the_flag_through(self, capsys, config_path, tmp_path, fake_weknora):
        (tmp_path / "out" / "个股_紫金").mkdir(parents=True)
        code, env = call(capsys, "push", "--kb", "库", "--stock", "紫金", "--dry-run", "--config", config_path)
        assert code == 0 and env["data"]["dry_run"] is True and fake_weknora == [("个股_紫金", True)]

    def test_unparsed_reports_are_a_partial_failure(self, monkeypatch, capsys, config_path, tmp_path):
        def broken(client, kb, root, emit, dry_run=False, timeout=600.0):
            return {"folder": root.name, "kb_id": kb["id"], "kb_name": kb["name"], "total": 2,
                    "already_in_kb": 0, "dry_run": dry_run, "uploaded": [], "completed": 0,
                    "failed": [{"file": "a.md", "error": "WeKnora 413"}]}

        monkeypatch.setattr(cli.weknora, "pick_kb", lambda *a, **k: {"id": "kb-1", "name": "库"})
        monkeypatch.setattr(cli.weknora, "push", broken)
        (tmp_path / "out" / "个股_紫金").mkdir(parents=True)
        code, env = call(capsys, "push", "--kb", "库", "--stock", "紫金", "--config", config_path)
        assert code == 5 and env["error"]["code"] == "partial_failure"
        assert env["data"]["failed"] == [{"folder": "个股_紫金", "file": "a.md", "error": "WeKnora 413"}]

    def test_an_unsaved_target_folder_is_a_config_error_with_the_real_options(self, monkeypatch, capsys,
                                                                             config_path, tmp_path):
        monkeypatch.setattr(cli.weknora, "pick_kb", lambda *a, **k: {"id": "kb-1", "name": "库"})
        (tmp_path / "out" / "个股_紫金").mkdir(parents=True)
        code, env = call(capsys, "push", "--kb", "库", "--stock", "不存在", "--config", config_path)
        assert code == 2 and env["error"]["code"] == "config_error"
        assert "个股_紫金" in env["error"]["message"]  # tell the agent what actually exists

    def test_pushing_nothing_at_all_is_a_config_error(self, monkeypatch, capsys, config_path, tmp_path):
        monkeypatch.setattr(cli.weknora, "pick_kb", lambda *a, **k: {"id": "kb-1", "name": "库"})
        (tmp_path / "out").mkdir()
        code, env = call(capsys, "push", "--kb", "库", "--config", config_path)
        assert code == 2 and "fetch" in env["error"]["message"]

    def test_config_without_credentials_says_where_to_put_them(self, monkeypatch, capsys, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("output_dir: out\n", encoding="utf-8")
        monkeypatch.delenv("WEKNORA_BASE_URL", raising=False)
        monkeypatch.delenv("WEKNORA_API_KEY", raising=False)
        (tmp_path / "out" / "个股_紫金").mkdir(parents=True)
        code, env = call(capsys, "push", "--kb", "库", "--stock", "紫金", "--config", str(path))
        assert code == 2 and "config.yaml" in env["error"]["message"]

    def test_jsonl_streams_push_events(self, capsys, config_path, tmp_path, fake_weknora):
        (tmp_path / "out" / "个股_紫金").mkdir(parents=True)
        code, env = call(capsys, "push", "--kb", "库", "--stock", "紫金", "--jsonl", "--config", config_path)
        assert code == 0 and env["event"] == "result" and env["ok"] is True


class TestSystemCli:
    """`hibor` 是装在 PATH 上的命令：init/spec 不能要求已有配置，其余命令缺配置要会说清下一步。"""

    @pytest.fixture
    def bare_environment(self, tmp_path, monkeypatch):
        """No config next to the cwd, none in the user dir, none in the environment.

        `cli` 里有两份 USER_CONFIG_DIR（自己的和 config 模块的搜索），都要挪进 tmp_path，
        否则测试会读写本机真实的 ~/.hibor。
        """
        home = tmp_path / "home"
        monkeypatch.setattr(config_mod, "USER_CONFIG_DIR", home)
        monkeypatch.setattr(cli, "USER_CONFIG_DIR", home)
        monkeypatch.delenv("HIBOR_CONFIG", raising=False)
        (tmp_path / "elsewhere").mkdir()
        monkeypatch.chdir(tmp_path / "elsewhere")
        return home

    def test_init_writes_the_user_config_needing_no_config(self, capsys, bare_environment):
        code, env = call(capsys, "init")
        assert code == 0
        assert Path(env["data"]["config"]) == bare_environment / "config.yaml"
        assert load_config(Path(env["data"]["config"]), environ={})  # the template really loads
        assert "hibor login" in env["data"]["next"][0]

    def test_init_to_an_explicit_path(self, capsys, bare_environment, tmp_path):
        code, env = call(capsys, "init", "--path", str(tmp_path / "cfg" / "config.yaml"),
                         "--profile-dir", "D:/hibor/profile")
        assert code == 0 and env["data"]["profile_dir"] == "D:/hibor/profile"
        assert load_config(Path(env["data"]["config"]), environ={}).profile_dir == Path("D:/hibor/profile")

    def test_second_init_refuses_to_clobber_and_suggests_force(self, capsys, bare_environment):
        call(capsys, "init")
        code, env = call(capsys, "init")
        assert code == 2 and "--force" in env["error"]["message"]

    def test_the_written_config_is_found_by_the_next_command(self, monkeypatch, capsys, bare_environment):
        call(capsys, "init")
        monkeypatch.setattr(cli, "profile_in_use", lambda _path: False)
        monkeypatch.setattr(cli, "browser_session", fake_session(FakePage(text={"退出登录": 1})))
        code, env = call(capsys, "doctor")
        assert code == 0 and env["data"]["config_path"] == str(bare_environment / "config.yaml")
        assert env["data"]["profile_dir"] == str(bare_environment / "chrome-profile")

    def test_a_command_without_any_config_tells_the_agent_to_run_init(self, capsys, bare_environment):
        code, env = call(capsys, "status")
        assert code == 2 and "hibor init" in env["error"]["message"]

    def test_spec_needs_no_config_and_reports_the_search_result(self, capsys, bare_environment):
        code, env = call(capsys, "spec")
        assert code == 0
        assert env["data"]["config_path"] is None
        assert "hibor init" in env["data"]["config_error"]
        assert set(env["data"]["exit_codes"]) == {"0", "1", "2", "3", "4", "5", "6"}
        described = {c["command"] for c in env["data"]["commands"]}
        assert {"hibor init", "hibor spec", "hibor stock list", "hibor stock fetch",
                "hibor industry list", "hibor industry fetch", "hibor status", "hibor push",
                "hibor doctor", "hibor industries", "hibor login"} == described

    def test_spec_names_the_config_it_would_use(self, capsys, config_path):
        code, env = call(capsys, "spec", "--config", config_path)
        assert code == 0 and env["data"]["config_path"] == str(Path(config_path))

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])
        assert exc.value.code == 0
        assert capsys.readouterr().out.strip() == f"hibor {__version__}"


class TestDoctorAndIndustries:
    def test_doctor_ok(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "profile_in_use", lambda _path: False)
        monkeypatch.setattr(cli, "browser_session", fake_session(FakePage(text={"退出登录": 1})))
        code, env = call(capsys, "doctor", "--config", config_path)
        assert code == 0 and env["data"]["logged_in"] is True and env["data"]["blocked"] is False
        assert env["data"]["profile_dir"].endswith("profile")
        assert env["data"]["config_path"] == str(Path(config_path).resolve())

    def test_doctor_not_logged_in(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "profile_in_use", lambda _path: False)
        monkeypatch.setattr(cli, "browser_session", fake_session(FakePage(text={})))
        code, env = call(capsys, "doctor", "--config", config_path)
        assert code == 3 and env["error"]["code"] == "login_required"

    def test_doctor_blank_page_means_blocked(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "profile_in_use", lambda _path: False)
        monkeypatch.setattr(cli, "browser_session", fake_session(FakePage(body_text="")))
        code, env = call(capsys, "doctor", "--config", config_path)
        assert code == 4 and env["error"]["code"] == "blocked"

    def test_doctor_profile_busy_skips_the_browser(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "profile_in_use", lambda _path: True)
        monkeypatch.setattr(cli, "browser_session",
                            lambda *a, **k: pytest.fail("must not open a browser"))
        code, env = call(capsys, "doctor", "--config", config_path)
        assert code == 6 and env["data"]["profile_busy"] is True

    def test_industries(self, monkeypatch, capsys, config_path, fixture_text):
        monkeypatch.setattr(cli, "browser_session", fake_session(FakePage([fixture_text("industry_list.html")])))
        code, env = call(capsys, "industries", "--config", config_path)
        assert code == 0 and [i["name"] for i in env["data"]["industries"]] == ["电子", "有色金属"]

    def test_industries_blank_page_is_blocked(self, monkeypatch, capsys, config_path):
        monkeypatch.setattr(cli, "browser_session", fake_session(FakePage(["<html></html>"])))
        code, env = call(capsys, "industries", "--config", config_path)
        assert code == 4 and env["error"]["code"] == "blocked"
