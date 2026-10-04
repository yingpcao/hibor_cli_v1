"""WeKnora client + push. The HTTP layer is a fake server, so no test reaches the network."""
import io
import json
import urllib.error
from urllib.parse import urlparse

import pytest

from hibor_cli import weknora
from hibor_cli.config import WeKnora
from hibor_cli.models import ConfigError, WeKnoraError, WeKnoraUnauthorizedError, WeKnoraUnreachableError

KB = {"id": "kb-1", "name": "RP-小金属", "description": "研报"}
LIST = "GET /knowledge-bases/kb-1/knowledge?page=1&page_size=100"
UPLOAD = "POST /knowledge-bases/kb-1/knowledge/file"


class Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeServer:
    """Answers by "METHOD path?query". A multi-item route is consumed one item per call, the last repeats."""

    def __init__(self):
        self.routes: dict[str, list] = {}
        self.calls: list[dict] = []

    def route(self, method, path, *payloads):
        self.routes[f"{method} {path}"] = list(payloads)
        return self

    def empty_kb(self, *existing):
        return self.route("GET", LIST.removeprefix("GET "),
                          {"data": [{"file_name": n} for n in existing], "total": len(existing)})

    def uploads(self, *payloads):
        return self.route("POST", UPLOAD.removeprefix("POST "), *payloads)

    def parsed(self, knowledge_id, status, **extra):
        return self.route("GET", f"/knowledge/{knowledge_id}", {"id": knowledge_id, "parse_status": status, **extra})

    def __call__(self, req, timeout=None):
        url = urlparse(req.full_url)
        path = url.path.removeprefix("/api/v1")
        key = f"{req.get_method()} {path}" + (f"?{url.query}" if url.query else "")
        self.calls.append({"key": key, "body": req.data, "headers": dict(req.header_items())})
        if key not in self.routes:
            raise AssertionError(f"unexpected request: {key}")
        answers = self.routes[key]
        value = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(value, Exception):
            raise value
        return Resp(value if "success" in value else {"success": True, "data": value})


def http_error(code, reason, body=None):
    return urllib.error.HTTPError("http://x", code, reason, {}, io.BytesIO((body or "").encode("utf-8")))


def served(server):
    return weknora.Client("http://x/api/v1", "sk-test", opener=server)


def folder(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_text("正文", encoding="utf-8")
    return tmp_path


class TestClient:
    def test_sends_the_api_key_header(self):
        server = FakeServer().route("GET", "/knowledge-bases", [KB])
        assert weknora.knowledge_bases(served(server)) == [KB]
        assert server.calls[0]["headers"]["X-api-key"] == "sk-test"

    def test_connection_failure_is_unreachable(self):
        server = FakeServer().route("GET", "/knowledge-bases", urllib.error.URLError("connection refused"))
        with pytest.raises(WeKnoraUnreachableError):
            weknora.knowledge_bases(served(server))

    def test_401_is_unauthorized_and_keeps_the_server_message(self):
        server = FakeServer().route("GET", "/knowledge-bases",
                                    http_error(401, "Unauthorized", '{"error":{"message":"invalid key"}}'))
        with pytest.raises(WeKnoraUnauthorizedError, match="invalid key"):
            weknora.knowledge_bases(served(server))

    def test_5xx_is_unreachable(self):
        server = FakeServer().route("GET", "/knowledge-bases", http_error(503, "Unavailable"))
        with pytest.raises(WeKnoraUnreachableError, match="503"):
            weknora.knowledge_bases(served(server))

    def test_4xx_stays_a_weknora_error(self):
        server = FakeServer().route("GET", "/knowledge-bases", http_error(400, "Bad Request"))
        with pytest.raises(WeKnoraError, match="400"):
            weknora.knowledge_bases(served(server))

    def test_success_false_envelope_raises(self):
        server = FakeServer().route("GET", "/knowledge-bases", {"success": False, "error": {"message": "nope"}})
        with pytest.raises(WeKnoraError, match="nope"):
            weknora.knowledge_bases(served(server))

    def test_non_json_body_still_reports_the_path(self):
        class NotJson:
            def read(self):
                return b"<html>gateway</html>"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with pytest.raises(WeKnoraError, match="不是 JSON"):
            weknora.knowledge_bases(weknora.Client("http://x/api/v1", "sk", opener=lambda req, timeout=None: NotJson()))

    def test_config_is_the_default_and_env_overrides_per_field(self):
        made = weknora.make_client(WeKnora("http://x/api/v1/", "sk-config"))
        assert made.base_url == "http://x/api/v1" and made.api_key == "sk-config"
        rotated = weknora.make_client(WeKnora("http://x/api/v1", "sk-config"),
                                      {"WEKNORA_BASE_URL": "http://y/", "WEKNORA_API_KEY": "sk-env"})
        assert (rotated.base_url, rotated.api_key) == ("http://y", "sk-env")
        only_key = weknora.make_client(WeKnora("http://x/api/v1", ""), {"WEKNORA_API_KEY": "sk-env"})
        assert (only_key.base_url, only_key.api_key) == ("http://x/api/v1", "sk-env")

    def test_missing_credentials_are_a_config_error(self):
        with pytest.raises(ConfigError, match="config.yaml"):
            weknora.make_client(WeKnora("", ""), {})


class TestKnowledgeBaseLookup:
    def test_by_name(self):
        server = FakeServer().route("GET", "/knowledge-bases", [KB])
        assert weknora.pick_kb(served(server), "RP-小金属") == KB

    def test_by_id_skips_the_listing(self):
        kb_id = "2b1321c5-a9c1-4e6f-8ca6-e3a770eab516"
        server = FakeServer().route("GET", f"/knowledge-bases/{kb_id}", KB)
        assert weknora.pick_kb(served(server), kb_id) == KB
        assert [c["key"] for c in server.calls] == [f"GET /knowledge-bases/{kb_id}"]

    def test_missing_name_lists_what_exists_and_suggests_create(self):
        server = FakeServer().route("GET", "/knowledge-bases", [KB])
        with pytest.raises(WeKnoraError, match="--create"):
            weknora.pick_kb(served(server), "RP-不存在")

    def test_create_posts_a_document_kb(self):
        server = FakeServer().route("GET", "/knowledge-bases", []).route("POST", "/knowledge-bases", KB)
        assert weknora.pick_kb(served(server), "RP-小金属", create=True, description="d") == KB
        assert json.loads(server.calls[-1]["body"]) == {"name": "RP-小金属", "description": "d", "type": "document"}


class TestInventory:
    def test_kb_files_paginates_until_a_short_page(self):
        full = {"data": [{"file_name": f"f{i}.md"} for i in range(weknora.PAGE_SIZE)], "total": 101}
        server = (FakeServer().route("GET", "/knowledge-bases/kb-1/knowledge?page=1&page_size=100", full)
                  .route("GET", "/knowledge-bases/kb-1/knowledge?page=2&page_size=100",
                         {"data": [{"file_name": "f100.md"}], "total": 101}))
        assert weknora.kb_files(served(server), "kb-1") == {f"f{i}.md" for i in range(101)}


class TestParsing:
    def test_waits_until_the_entry_is_terminal(self):
        server = FakeServer().route("GET", "/knowledge/k1", {"id": "k1", "parse_status": "processing"},
                                    {"id": "k1", "parse_status": "completed"})
        out = weknora.wait_parsed(served(server), ["k1"], sleep=lambda s: None, timeout=30, poll=1)
        assert out[0]["parse_status"] == "completed"

    def test_returns_still_pending_entries_when_the_deadline_passes(self):
        server = FakeServer().route("GET", "/knowledge/k1", {"id": "k1", "parse_status": "pending"})
        out = weknora.wait_parsed(served(server), ["k1"], sleep=lambda s: None, timeout=0, poll=5)
        assert out[0]["parse_status"] == "pending"


class TestPush:
    def push(self, server, root, emit=None, **kwargs):
        return weknora.push(served(server), KB, root, emit, sleep=lambda s: None, timeout=0, **kwargs)

    def test_uploads_every_report_and_waits_for_parsing(self, tmp_path):
        server = FakeServer().empty_kb().uploads({"id": "k1", "parse_status": "pending"},
                                                 {"id": "k2", "parse_status": "pending"}).parsed("k1", "completed")
        server.parsed("k2", "completed")
        data = self.push(server, folder(tmp_path, "a.md", "b.md"))
        assert (data["total"], len(data["uploaded"]), data["completed"], data["failed"]) == (2, 2, 2, [])
        assert [c["key"] for c in server.calls] == [LIST, UPLOAD, UPLOAD, "GET /knowledge/k1", "GET /knowledge/k2"]
        assert data["folder"] == tmp_path.name

    def test_sends_the_filename_as_utf8_not_the_local_codepage(self, tmp_path):
        name = "2026-09-23_中钨高新-钨产业链领军者.md"
        server = FakeServer().empty_kb().uploads({"id": "k1", "parse_status": "pending"}).parsed("k1", "completed")
        self.push(server, folder(tmp_path, name))
        upload_call = next(c for c in server.calls if c["key"] == UPLOAD)
        assert f'filename="{name}"'.encode("utf-8") in upload_call["body"]
        assert "multipart/form-data" in upload_call["headers"]["Content-type"]

    def test_skips_files_already_in_the_kb(self, tmp_path):
        server = (FakeServer().empty_kb("a.md").uploads({"id": "k2", "parse_status": "pending"})
                  .parsed("k2", "completed"))
        data = self.push(server, folder(tmp_path, "a.md", "b.md"))
        assert data["already_in_kb"] == 1 and [i["file"] for i in data["uploaded"]] == ["b.md"]

    def test_dry_run_lists_without_uploading(self, tmp_path):
        server = FakeServer().empty_kb("a.md")
        data = self.push(server, folder(tmp_path, "a.md", "b.md"), dry_run=True)
        assert data["would_upload"] == ["b.md"] and data["already_in_kb"] == 1 and data["uploaded"] == []
        assert [c["key"] for c in server.calls] == [LIST]

    def test_a_rejected_file_does_not_stop_the_folder(self, tmp_path):
        server = (FakeServer().empty_kb().uploads(http_error(413, "Payload Too Large"),
                                                  {"id": "k2", "parse_status": "pending"})
                  .parsed("k2", "completed"))
        data = self.push(server, folder(tmp_path, "a.md", "b.md"))
        assert [i["file"] for i in data["uploaded"]] == ["b.md"]
        assert len(data["failed"]) == 1 and data["failed"][0]["file"] == "a.md"

    def test_failed_parsing_is_reported(self, tmp_path):
        server = (FakeServer().empty_kb().uploads({"id": "k1", "parse_status": "pending"})
                  .parsed("k1", "failed", error_message="unsupported file"))
        data = self.push(server, folder(tmp_path, "a.md"))
        assert data["completed"] == 0 and data["failed"] == [{"file": "a.md", "knowledge_id": "k1",
                                                             "parse_status": "failed",
                                                             "error": "unsupported file"}]

    def test_timeout_is_reported_as_failure(self, tmp_path):
        server = FakeServer().empty_kb().uploads({"id": "k1", "parse_status": "pending"}).parsed("k1", "processing")
        data = self.push(server, folder(tmp_path, "a.md"))
        assert data["failed"][0]["parse_status"] == "processing" and "超时" in data["failed"][0]["error"]

    def test_emits_events_for_agents(self, tmp_path):
        server = FakeServer().empty_kb().uploads({"id": "k1", "parse_status": "pending"}).parsed("k1", "completed")
        seen = []

        class Spy:
            def event(self, name, human="", **fields):
                seen.append(name)

        self.push(server, folder(tmp_path, "a.md"), Spy())
        assert seen == ["uploaded", "push_done"]
