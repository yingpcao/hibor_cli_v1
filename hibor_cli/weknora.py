"""WeKnora REST client plus the `output folder -> knowledge base` push behind `hibor push`.

Credentials come from the environment (`WEKNORA_BASE_URL`, `WEKNORA_API_KEY`) and those win over
config.yaml, so a long-lived key never has to live in the repo. Prints nothing: like the rest of the
library it returns plain dicts and lets the CLI do the output.
"""
import json
import mimetypes
import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import WeKnora
from .detail import reports_in
from .models import ConfigError, WeKnoraError, WeKnoraUnauthorizedError, WeKnoraUnreachableError

PAGE_SIZE = 100
UUID_CHARS = set("0123456789abcdef-")
TERMINAL = ("completed", "failed")


@dataclass(frozen=True)
class Client:
    base_url: str
    api_key: str
    opener: Callable[..., Any] = urllib.request.urlopen
    timeout: float = 30.0

    def request(self, method: str, path: str, payload: Any = None, *, body: bytes | None = None,
                content_type: str = "application/json") -> Any:
        if body is None and payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=body, method=method,
                                     headers={"X-API-Key": self.api_key, "Content-Type": content_type})
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                return _data(json.loads(resp.read().decode("utf-8")), path)
        except urllib.error.HTTPError as exc:
            raise _http_error(exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise WeKnoraUnreachableError(f"WeKnora 无法访问 {self.base_url}: {reason}") from exc
        except json.JSONDecodeError as exc:
            raise WeKnoraError(f"WeKnora 在 {path} 返回的不是 JSON: {exc}") from exc


def make_client(config: WeKnora, environ: Mapping[str, str] | None = None, opener: Callable | None = None,
                timeout: float = 30.0) -> Client:
    """config.yaml holds the address; the matching env var still wins, so a key can be rotated for
    one run without editing (or leaking into) the file."""
    env = os.environ if environ is None else environ
    base = (env.get("WEKNORA_BASE_URL") or config.base_url).rstrip("/")
    key = env.get("WEKNORA_API_KEY") or config.api_key
    if not base or not key:
        raise ConfigError("未配置 WeKnora：请在 config.yaml 的 weknora 段填写 base_url 与 api_key"
                          "（或用环境变量 WEKNORA_BASE_URL / WEKNORA_API_KEY）")
    return Client(base, key, opener or urllib.request.urlopen, timeout)


def _data(payload: dict, path: str) -> Any:
    if payload.get("success") is False:
        message = (payload.get("error") or {}).get("message") or str(payload)
        raise WeKnoraError(f"WeKnora 在 {path} 返回失败: {message}")
    return payload.get("data")


def _http_error(exc: urllib.error.HTTPError) -> WeKnoraError:
    try:
        detail = (json.loads(exc.read().decode("utf-8", "replace")).get("error") or {}).get("message", "")
    except Exception:  # proxies can answer with anything, the status code is still the useful part
        detail = ""
    message = f"WeKnora {exc.code}: {detail or exc.reason}"
    if exc.code in (401, 403):
        return WeKnoraUnauthorizedError(message)
    if exc.code >= 500:
        return WeKnoraUnreachableError(message)
    return WeKnoraError(message)


def _multipart(path: Path, fields: Mapping[str, str] | None = None) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                   for k, v in (fields or {}).items())
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    file_part = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n").encode("utf-8") + path.read_bytes() + b"\r\n"
    return (head.encode("utf-8") + file_part + f"--{boundary}--\r\n".encode("utf-8"),
            f"multipart/form-data; boundary={boundary}")


def knowledge_bases(client: Client) -> list[dict]:
    return client.request("GET", "/knowledge-bases") or []


def pick_kb(client: Client, name_or_id: str, *, create: bool = False, description: str = "") -> dict:
    """Resolve a KB by id or exact name; `create` makes a missing one instead of failing."""
    if len(name_or_id) == 36 and set(name_or_id) <= UUID_CHARS:
        return client.request("GET", f"/knowledge-bases/{name_or_id}")
    known = knowledge_bases(client)
    for kb in known:
        if kb.get("name") == name_or_id:
            return kb
    if not create:
        raise WeKnoraError(f"知识库 {name_or_id!r} 不存在，可用: {sorted(k.get('name', '') for k in known)}；"
                           "确认名字或加 --create 新建")
    return client.request("POST", "/knowledge-bases",
                          {"name": name_or_id, "description": description, "type": "document"})


def kb_files(client: Client, kb_id: str) -> set[str]:
    """File names already in the KB, so a repeated push uploads nothing."""
    seen: set[str] = set()
    page = 1
    while True:
        data = client.request("GET", f"/knowledge-bases/{kb_id}/knowledge?page={page}&page_size={PAGE_SIZE}")
        rows = data if isinstance(data, list) else data.get("data", [])
        seen.update(row.get("file_name") or row.get("title") or "" for row in rows)
        if isinstance(data, list) or len(rows) < PAGE_SIZE:
            return seen
        page += 1


def upload(client: Client, kb_id: str, path: Path) -> dict:
    body, ctype = _multipart(path, {"enable_multimodel": "true"})
    return client.request("POST", f"/knowledge-bases/{kb_id}/knowledge/file", body=body, content_type=ctype)


def wait_parsed(client: Client, ids: list[str], *, sleep: Callable[[float], None], timeout: float,
                poll: float = 3.0) -> list[dict]:
    """Poll until every entry reaches completed/failed, or the deadline passes; timed-out ones come back as-is."""
    waited, todo, done = 0.0, list(ids), {}
    while todo:
        for knowledge_id in list(todo):
            entry = client.request("GET", f"/knowledge/{knowledge_id}")
            if entry.get("parse_status") in TERMINAL:
                done[knowledge_id] = entry
                todo.remove(knowledge_id)
        if not todo or waited >= timeout:
            break
        sleep(poll)
        waited += poll
    done.update({k: client.request("GET", f"/knowledge/{k}") for k in todo})
    return [done[i] for i in ids if i in done]


def push(client: Client, kb: dict, root: Path, emit: Any = None, *, dry_run: bool = False,
         sleep: Callable[[float], None] = lambda s: None, timeout: float = 600.0,
         poll: float = 3.0) -> dict:
    """Upload one folder into `kb`. Files already in the KB are skipped, so it is safe to re-run."""
    files = reports_in(root)
    already = kb_files(client, kb["id"])
    todo = [f for f in files if f.name not in already]
    data: dict[str, Any] = {"folder": root.name, "kb_id": kb["id"], "kb_name": kb.get("name", ""),
                            "total": len(files), "already_in_kb": len(files) - len(todo),
                            "dry_run": dry_run, "uploaded": [], "failed": []}
    if dry_run:
        data["would_upload"] = [f.name for f in todo]
        if emit:
            emit.event("push_plan", f"[{root.name} -> {kb.get('name')}] 待上传 {len(todo)} 篇，"
                                    f"已在库 {data['already_in_kb']} 篇", **data)
        return data
    for f in todo:
        try:
            entry = upload(client, kb["id"], f)
        except WeKnoraError as exc:  # one bad file must not stop the folder
            data["failed"].append({"file": f.name, "error": str(exc)})
            if emit:
                emit.event("failed", f"[{root.name}] 上传失败 {f.name}: {exc}", file=f.name, error=str(exc))
            continue
        data["uploaded"].append({"file": f.name, "knowledge_id": entry["id"],
                                 "parse_status": entry.get("parse_status", "pending")})
        if emit:
            emit.event("uploaded", f"[{root.name}] 已上传 {f.name}", file=f.name, knowledge_id=entry["id"])
    by_id = {p["id"]: p for p in wait_parsed(client, [u["knowledge_id"] for u in data["uploaded"]],
                                             sleep=sleep, timeout=timeout, poll=poll)}
    for item in data["uploaded"]:
        entry = by_id.get(item["knowledge_id"], {})
        item["parse_status"] = entry.get("parse_status", item["parse_status"])
        if item["parse_status"] != "completed":
            data["failed"].append({"file": item["file"], "knowledge_id": item["knowledge_id"],
                                   "parse_status": item["parse_status"],
                                   "error": entry.get("error_message") or "解析未完成（超时）"})
    data["completed"] = sum(1 for i in data["uploaded"] if i["parse_status"] == "completed")
    if emit:
        emit.event("push_done", f"[{root.name} -> {kb.get('name')}] 上传 {len(data['uploaded'])} 篇，"
                                f"解析完成 {data['completed']} 篇，失败 {len(data['failed'])} 篇", **data)
    return data
