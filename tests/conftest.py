import sys
from pathlib import Path

import pytest

from hibor_cli import cli
from hibor_cli.config import Delay, Settings, WeKnora

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"

CONFIG = """
output_dir: out
state_dir: state
profile_dir: profile
delay: {detail: [0, 0], page: [0, 0], batch_size: 5, batch_pause: [0, 0]}
weknora: {base_url: "http://weknora.test/api/v1", api_key: sk-test}
"""


@pytest.fixture
def fixture_text():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return read


@pytest.fixture
def config_path(tmp_path):
    """Config pointing at tmp_path, so the real `output/`, `state/` and Chrome profile stay untouched."""
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return str(path)


@pytest.fixture
def settings(tmp_path):
    return Settings(base_dir=tmp_path, output_dir=tmp_path / "out", db_path=tmp_path / "state" / "reports.db",
                    profile_dir=tmp_path / "profile", headless=True, delay=Delay((0, 0), (0, 0), 25, (0, 0)),
                    max_consecutive_failures=3, weknora=WeKnora("http://weknora.test/api/v1", "sk-test"))


@pytest.fixture
def fake_weknora(monkeypatch):
    """Stand in for the WeKnora round trip: push tests assert the envelope, not the HTTP layer."""
    calls = []
    monkeypatch.setattr(cli.weknora, "pick_kb",
                        lambda client, name, create=False, description="": {"id": "kb-1", "name": name})
    monkeypatch.setattr(cli.weknora, "push",
                        lambda client, kb, root, emit, dry_run=False, timeout=600.0: calls.append(
                            (root.name, dry_run)) or {"folder": root.name, "kb_id": kb["id"],
                                                      "kb_name": kb["name"], "total": 1, "already_in_kb": 0,
                                                      "dry_run": dry_run,
                                                      "uploaded": [{"file": "a.md", "knowledge_id": "k1",
                                                                    "parse_status": "completed"}],
                                                      "completed": 1, "failed": [], "would_upload": ["a.md"]})
    return calls
