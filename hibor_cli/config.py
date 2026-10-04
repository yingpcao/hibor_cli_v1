"""Load and validate config.yaml into immutable settings.

v1 has no job list: what to crawl comes from the command line (`hibor stock 紫金 --days 30`), so
config.yaml only holds paths, pacing and the WeKnora target.

The CLI is also installed as a system command (`uv tool install`), where "next to the code" means an
ephemeral venv, so a config is found by search rather than by package location:
`--config` > `HIBOR_CONFIG` > ./config.yaml > ~/.hibor/config.yaml. `hibor init` writes the last one.
Paths inside a config file are relative to that file's directory, which is what makes the
user-level config self-contained (`~/.hibor/output`, `~/.hibor/state`, `~/.hibor/chrome-profile`).
"""
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import ConfigError

CONFIG_FILENAME = "config.yaml"
USER_CONFIG_DIR = Path.home() / ".hibor"
CONFIG_TEMPLATE = """\
# hibor CLI 配置。这里的相对路径都以本文件所在目录为基准。
output_dir: output
state_dir: state

# 登录态 = 这个 Chrome 配置目录（profile 就是 session，不要把 cookie 导出给别的客户端）。
# 同一时刻只允许一个进程用它，并发的第二个退出码 6。也可用环境变量 HIBOR_PROFILE_DIR 覆盖。
profile_dir: chrome-profile

headless: false              # 建议保持 false：真实窗口更不容易被风控

# 抓取节奏。这是照着人工浏览的节奏定的，请勿调低 —— 站点在 safedog 后面，
# 被判定为机器就会用「HTTP 200 + 空白页」回你（退出码 4）。
delay:
  detail: [3, 8]             # 详情页间隔（秒，随机）
  page: [2, 4]               # 列表翻页间隔
  batch_size: 25             # 每 N 篇长休息一次
  batch_pause: [20, 40]
max_consecutive_failures: 3  # 连续失败这么多篇就判定被风控，中止（退出码 4）

# WeKnora 知识库（`hibor push --kb ...` 的目标）。密钥走环境变量 WEKNORA_API_KEY / WEKNORA_BASE_URL，
# 写在文件里就别把目录分享出去、也别提交到仓库。
weknora:
  base_url: ""
  api_key: ""
"""


@dataclass(frozen=True)
class Delay:
    detail: tuple[float, float] = (3.0, 8.0)
    page: tuple[float, float] = (2.0, 4.0)
    batch_size: int = 25
    batch_pause: tuple[float, float] = (20.0, 40.0)


@dataclass(frozen=True)
class WeKnora:
    """Where `push` uploads. The matching env vars win, so a key can be rotated for one run."""

    base_url: str = ""
    api_key: str = ""


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    output_dir: Path
    db_path: Path
    profile_dir: Path
    config_path: Path = Path(CONFIG_FILENAME)
    headless: bool = False
    delay: Delay = Delay()
    max_consecutive_failures: int = 3
    weknora: WeKnora = WeKnora()


KNOWN_KEYS = {"output_dir", "state_dir", "profile_dir", "headless", "delay",
              "max_consecutive_failures", "weknora"}


def _pair(value: Any, name: str) -> tuple[float, float]:
    try:
        low, high = value
        low, high = float(low), float(high)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} 应为 [最小, 最大] 秒") from exc
    if not 0 <= low <= high:
        raise ConfigError(f"{name} 需满足 0 <= 最小 <= 最大: {value!r}")
    return low, high


def _delay(raw: Mapping[str, Any]) -> Delay:
    base = Delay()
    return Delay(
        detail=_pair(raw.get("detail", base.detail), "delay.detail"),
        page=_pair(raw.get("page", base.page), "delay.page"),
        batch_size=int(raw.get("batch_size", base.batch_size)),
        batch_pause=_pair(raw.get("batch_pause", base.batch_pause), "delay.batch_pause"),
    )


def _weknora(raw: Mapping[str, Any]) -> WeKnora:
    return WeKnora(str(raw.get("base_url") or "").rstrip("/"), str(raw.get("api_key") or ""))


def _max_failures(raw: Mapping[str, Any]) -> int:
    try:
        value = int(raw.get("max_consecutive_failures", 3))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"max_consecutive_failures 应为整数: {raw.get('max_consecutive_failures')!r}") from exc
    if value < 1:
        raise ConfigError(f"max_consecutive_failures 至少为 1: {value}")
    return value


def resolve_config_path(explicit: str | Path | None = None, cwd: Path | None = None,
                        environ: Mapping[str, str] | None = None) -> Path:
    """`--config` > `HIBOR_CONFIG` > ./config.yaml > ~/.hibor/config.yaml；都不存在就是可操作的报错。"""
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise ConfigError(f"找不到配置文件: {path}")
        return path
    env = os.environ if environ is None else environ
    from_env = env.get("HIBOR_CONFIG")
    if from_env:
        path = Path(from_env)
        if not path.exists():
            raise ConfigError(f"HIBOR_CONFIG 指向的文件不存在: {path}")
        return path
    here = Path.cwd() if cwd is None else cwd
    for path in (here / CONFIG_FILENAME, USER_CONFIG_DIR / CONFIG_FILENAME):
        if path.exists():
            return path
    raise ConfigError(
        f"没找到配置（依次查过 {here / CONFIG_FILENAME}、{USER_CONFIG_DIR / CONFIG_FILENAME}）。"
        f"先运行 `hibor init` 写出 {USER_CONFIG_DIR / CONFIG_FILENAME}，或用 --config 指定路径")


def write_config(path: Path, profile_dir: str | Path | None = None, force: bool = False) -> Path:
    """`hibor init`: drop the template somewhere the user can edit. Refuses to overwrite silently."""
    if path.exists() and not force:
        raise ConfigError(f"{path} 已存在；确认要覆盖再加 --force")
    profile = Path(profile_dir).as_posix() if profile_dir else "chrome-profile"
    text = CONFIG_TEMPLATE.replace("profile_dir: chrome-profile", f'profile_dir: "{profile}"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def load_config(path: Path, environ: Mapping[str, str] | None = None) -> Settings:
    """Paths in config.yaml are relative to the config file, so the project can run from anywhere.
    `HIBOR_PROFILE_DIR` overrides `profile_dir` for one run (the profile is the login)."""
    if not path.exists():
        raise ConfigError(f"找不到配置文件: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    env = os.environ if environ is None else environ
    unknown = set(raw) - KNOWN_KEYS
    if unknown:
        raise ConfigError(f"config.yaml 含未知字段: {sorted(unknown)}")
    delay_raw = {k: v for k, v in raw.items() if k == "delay"}
    base = path.resolve().parent
    profile = env.get("HIBOR_PROFILE_DIR") or str(raw.get("profile_dir") or "state/chrome-profile")
    state_dir = base / str(raw.get("state_dir", "state"))
    return Settings(
        base_dir=base,
        output_dir=base / str(raw.get("output_dir", "output")),
        db_path=state_dir / "reports.db",
        profile_dir=Path(profile) if Path(profile).is_absolute() else base / profile,
        config_path=path.resolve(),
        headless=bool(raw.get("headless", False)),
        delay=_delay(delay_raw.get("delay") or {}),
        max_consecutive_failures=_max_failures(raw),
        weknora=_weknora(raw.get("weknora") or {}),
    )
