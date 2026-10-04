"""技能包（skills/hibor-reports）与 CLI 真实接口不能各说各话。

技能是给 agent 读的说明书；它一旦写了不存在的 flag 或漏了某条命令，agent 就会照着猜。
所以这里把 SKILL.md / references 里的命令与参数拿去和 `hibor spec` 的契约对账。
"""
import re
from pathlib import Path

import pytest

from hibor_cli import cli
from hibor_cli.spec import COMMANDS, CONVENTIONS, EXIT_CODES

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "hibor-reports"
BY_NAME = {c["command"].removeprefix("hibor "): c for c in COMMANDS}

# 安装脚本自己的参数，不是 hibor 的
INSTALLER_FLAGS = {"--skill", "--source", "--bin-dir", "--dry-run", "--yes", "--reinstall", "--help"}
FLAG_TOKEN = re.compile(r"--[a-z][\w-]*")
COMMAND_TOKEN = re.compile(r"\bhibor (init|spec|stock|industry|status|push|doctor|industries|login)\b")


def _flags(entry) -> list[dict]:
    args = entry["args"]
    if isinstance(args, str):  # "same as stock list"
        args = BY_NAME[args.removeprefix("same as ")]["args"]
    return args


REAL_FLAGS = {a["flag"] for e in COMMANDS for a in _flags(e) if a["flag"].startswith("--")} | {"--version"}


@pytest.fixture(scope="module")
def skill_md() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def commands_md() -> str:
    return (SKILL_DIR / "references" / "commands.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def troubleshooting_md() -> str:
    return (SKILL_DIR / "references" / "troubleshooting.md").read_text(encoding="utf-8")


class TestLayout:
    @pytest.mark.parametrize("relative", ["SKILL.md", "references/commands.md", "references/routing-guide.md",
                                           "references/troubleshooting.md", "scripts/setup.ps1", "scripts/setup.sh",
                                           "scripts/setup.cjs"])
    def test_the_packaged_files_exist(self, relative):
        assert (SKILL_DIR / relative).is_file(), relative

    def test_frontmatter_has_what_a_skill_host_needs(self, skill_md):
        front = skill_md.split("---")[1]
        fields = dict(re.findall(r"^(\w+): (.*)$", front, re.MULTILINE))
        assert fields["name"] == "hibor-reports"
        assert fields["version"].startswith("1.")
        # description 是路由依据：得说清用在哪、不能用什么
        assert "hibor" in fields["description"] and "研报" in fields["description"]
        assert len(fields["description"]) > 80

    def test_body_is_not_a_copy_of_the_readme(self, skill_md):
        assert "全文已入库" in skill_md  # 明确禁止的说法
        assert "hibor init" in skill_md and "hibor login" in skill_md  # 系统级安装后的前两步


class TestCommandCoverage:
    def test_every_spec_command_is_documented_in_references(self, commands_md):
        # commands.md 把 list/fetch 合写在一个小节里，所以按「前缀 + 动词」匹配标题
        headings = re.findall(r"(?m)^## (hibor .+)$", commands_md)
        missing = [c["command"] for c in COMMANDS
                   if not any(h.startswith(" ".join(c["command"].split()[:2]))
                              and re.search(rf"\b{c['command'].split()[-1]}\b", h) for h in headings)]
        assert not missing

    def test_skill_md_only_names_commands_that_exist(self, skill_md):
        groups = {c["command"].split()[1] for c in COMMANDS}
        named = set(COMMAND_TOKEN.findall(skill_md))
        assert named <= groups
        assert {"stock", "push", "status", "doctor"} <= named

    def test_no_flag_in_the_skill_body_invents_an_option(self, skill_md, commands_md):
        for text, where in ((skill_md, "SKILL.md"), (commands_md, "commands.md")):
            bogus = set(FLAG_TOKEN.findall(text)) - INSTALLER_FLAGS - REAL_FLAGS
            assert not bogus, f"{where} 写了不存在的参数: {sorted(bogus)}"

    def test_every_real_flag_is_documented(self, commands_md):
        for command in sorted(BY_NAME):
            for arg in _flags(BY_NAME[command]):
                if arg["flag"].startswith("--"):
                    assert arg["flag"] in commands_md, f"{command}: {arg['flag']} 没写进 commands.md"


class TestExitCodeGuidance:
    def test_every_exit_code_has_advice_in_the_skill(self, skill_md):
        for code in sorted({str(c) for c in EXIT_CODES.values()}):
            assert re.search(rf"^\| {code} \|", skill_md, re.MULTILINE), code

    def test_the_login_exception_is_stated(self, skill_md):
        # 这是 agent 最容易误判的一条：doctor 说没登录 ≠ 抓不到
        assert "不代表抓不到" in skill_md


class TestEncodingGuidance:
    """PowerShell 5.1 按 GBK 解码子进程字节，会把中文后面的右引号一起吃掉，JSON 就解不开。

    字节本身没错（cmd/Git Bash 都能解析），所以修法只能是「告诉调用方先切 UTF-8」，
    这条坑必须同时出现在契约和技能文档里，否则 agent 会以为是 CLI 坏了。
    """

    def test_the_convention_names_the_decode_trap(self):
        text = " ".join(CONVENTIONS)
        assert "ConvertFrom-Json" in text and "[Console]::OutputEncoding" in text

    def test_the_skill_and_its_troubleshooting_carry_the_recipe(self, skill_md, troubleshooting_md):
        for text in (skill_md, troubleshooting_md):
            assert "ConvertFrom-Json" in text and "[Console]::OutputEncoding=[Text.Encoding]::UTF8" in text
