from pathlib import Path

import pytest

from hibor_cli import config as config_mod
from hibor_cli.config import CONFIG_FILENAME, load_config, resolve_config_path, write_config
from hibor_cli.models import ConfigError

BASE = "output_dir: out\n"


def write(tmp_path, text: str) -> Path:
    """Write a config into a directory, creating it — the resolve tests need several of these."""
    dir_ = Path(tmp_path)
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def no_home_config(tmp_path, monkeypatch):
    """把 ~/.hibor 挪进 tmp_path，这样测试与本机真实用户目录无关。"""
    home = tmp_path / "home"
    monkeypatch.setattr(config_mod, "USER_CONFIG_DIR", home)
    return home


class TestLoad:
    def test_paths_are_relative_to_the_config_file(self, tmp_path):
        (tmp_path / "sub").mkdir()
        settings = load_config(write(tmp_path / "sub", BASE), environ={})
        assert settings.output_dir == tmp_path / "sub" / "out"
        assert settings.db_path == tmp_path / "sub" / "state" / "reports.db"
        assert settings.profile_dir == tmp_path / "sub" / "state" / "chrome-profile"

    def test_every_field_is_read(self, tmp_path, config_path):
        settings = load_config(Path(config_path), environ={})
        assert (settings.delay.detail, settings.delay.page, settings.delay.batch_size) == \
               ((0.0, 0.0), (0.0, 0.0), 5)
        assert settings.weknora.base_url == "http://weknora.test/api/v1"
        assert settings.headless is False and settings.max_consecutive_failures == 3

    def test_env_overrides_the_profile_dir_for_one_run(self, tmp_path):
        settings = load_config(write(tmp_path, BASE), {"HIBOR_PROFILE_DIR": "D:/other/profile"})
        assert settings.profile_dir == Path("D:/other/profile")

    def test_absolute_profile_dir_is_kept(self, tmp_path):
        path = write(tmp_path, "profile_dir: D:/hibor/profile\n")
        assert load_config(path, environ={}).profile_dir == Path("D:/hibor/profile")

    def test_unknown_key_is_rejected_rather_than_ignored(self, tmp_path):
        with pytest.raises(ConfigError, match="jobs"):
            load_config(write(tmp_path, BASE + "jobs: []\n"), environ={})

    @pytest.mark.parametrize("line", ["delay: {detail: [8, 3]}", "delay: {detail: [a, b]}",
                                      "delay: {detail: [-1, 2]}", "max_consecutive_failures: x"])
    def test_bad_values_are_config_errors(self, tmp_path, line):
        with pytest.raises(ConfigError):
            load_config(write(tmp_path, line + "\n"), environ={})

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError):
            load_config(tmp_path / "nope.yaml", environ={})

    def test_config_path_is_recorded(self, tmp_path):
        path = write(tmp_path, BASE)
        assert load_config(path, environ={}).config_path == path.resolve()


class TestResolveConfigPath:
    """系统级安装后没有「代码旁边的 config.yaml」，所以配置按顺序搜。"""

    def test_explicit_flag_wins_over_everything(self, tmp_path, no_home_config):
        here = tmp_path / "cwd"
        here.mkdir()
        write(here, BASE)
        write(no_home_config, BASE)
        explicit = write(tmp_path / "elsewhere", BASE)
        assert resolve_config_path(explicit, cwd=here, environ={}) == explicit

    def test_env_var_beats_the_search(self, tmp_path, no_home_config):
        from_env = write(tmp_path / "e", BASE)
        assert resolve_config_path(None, cwd=tmp_path, environ={"HIBOR_CONFIG": str(from_env)}) == from_env

    def test_a_missing_env_target_is_an_error_not_a_fallthrough(self, tmp_path, no_home_config):
        with pytest.raises(ConfigError, match="HIBOR_CONFIG"):
            resolve_config_path(None, cwd=tmp_path, environ={"HIBOR_CONFIG": str(tmp_path / "gone.yaml")})

    def test_project_config_wins_over_the_user_one(self, tmp_path, no_home_config):
        write(no_home_config, BASE)
        here = write(tmp_path, BASE)
        assert resolve_config_path(None, cwd=tmp_path, environ={}) == here

    def test_user_config_is_the_last_stop(self, tmp_path, no_home_config):
        user = write(no_home_config, BASE)
        assert resolve_config_path(None, cwd=tmp_path / "empty", environ={}) == user

    def test_no_config_at_all_tells_the_agent_to_run_init(self, tmp_path, no_home_config):
        with pytest.raises(ConfigError, match="hibor init"):
            resolve_config_path(None, cwd=tmp_path, environ={})

    def test_a_bad_explicit_path_says_so(self, tmp_path, no_home_config):
        with pytest.raises(ConfigError, match="找不到配置文件"):
            resolve_config_path(tmp_path / "nope.yaml", cwd=tmp_path, environ={})


class TestWriteConfig:
    def test_creates_a_loadable_config_with_parents(self, tmp_path):
        path = tmp_path / ".hibor" / CONFIG_FILENAME
        assert write_config(path) == path
        settings = load_config(path, environ={})
        assert settings.output_dir == path.parent / "output"
        assert settings.profile_dir == path.parent / "chrome-profile"
        assert settings.delay.detail == (3.0, 8.0)

    def test_profile_dir_is_written_as_a_posix_path_and_reads_back(self, tmp_path):
        path = tmp_path / "config.yaml"
        write_config(path, profile_dir="D:/HiborAgent/hibor-web/state/chrome-profile")
        assert load_config(path, environ={}).profile_dir == Path("D:/HiborAgent/hibor-web/state/chrome-profile")

    def test_refuses_to_overwrite_unless_forced(self, tmp_path):
        path = write_config(tmp_path / "config.yaml")
        with pytest.raises(ConfigError, match="--force"):
            write_config(path)
        assert write_config(path, force=True) == path
