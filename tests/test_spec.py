"""`hibor spec` 不能和真正的 argparse 接口漂移：逐条命令拿 `--help` 的实际输出对账。"""
import re

import pytest

from hibor_cli import cli
from hibor_cli.spec import COMMANDS, EXIT_CODES, INTERNAL_ONLY_CODES, SPEC

_BY_NAME = {c["command"].removeprefix("hibor "): c for c in COMMANDS}
_OPTION_LINE = re.compile(r"^  (?:-\w, )?(--[\w-]+)")


def help_text(argv, capsys) -> set[str]:
    """The flags argparse itself advertises for one command."""
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*argv, "--help"])
    out = capsys.readouterr().out
    return {m.group(1) for line in out.splitlines() if (m := _OPTION_LINE.match(line))} - {"--help"}


def spec_flags(command: str) -> set[str]:
    args = _BY_NAME[command]["args"]
    if isinstance(args, str):  # "same as stock list"
        args = _BY_NAME[args.removeprefix("same as ")]["args"]
    return {a["flag"] for a in args if a["flag"].startswith("--")}


@pytest.mark.parametrize("command", sorted(_BY_NAME))
def test_spec_lists_exactly_the_flags_the_parser_accepts(command, capsys):
    assert spec_flags(command) == help_text(command.split(), capsys)


def test_every_documented_exit_code_maps_to_a_real_number():
    assert set(SPEC["exit_codes"]) == {str(code) for code in EXIT_CODES.values()}


def test_error_codes_all_have_an_exit_code():
    from hibor_cli import models

    for name, exc in vars(models).items():
        if isinstance(exc, type) and issubclass(exc, models.HiborError) and exc is not models.HiborError:
            assert exc.code in EXIT_CODES or exc.code in INTERNAL_ONLY_CODES, name


def test_spec_carries_the_envelope_and_the_gates():
    assert SPEC["envelope"]["shape"]["ok"] == "bool"
    assert [g["gate"] for g in SPEC["relevance_gates"]] == ["标题闸", "公司/行业二分", "噪音闸", "正文闸"]


def test_spec_is_json_serialisable(capsys):
    cli.main(["spec", "--config", "does/not/matter"])  # spec works without a config
    import json

    json.loads(capsys.readouterr().out)
