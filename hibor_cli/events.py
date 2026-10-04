"""Output channel. stdout is machine-readable only; human progress always goes to stderr.

- default:  one JSON envelope on stdout when the command finishes
- --jsonl:  one JSON object per line on stdout (events, then a final {"event": "result", ...})
Envelope: {"ok": bool, "data": {...} | null, "error": {"code", "message"} | null}
"""
import json
import sys
from typing import Any, TextIO


class Emitter:
    def __init__(self, jsonl: bool = False, out: TextIO | None = None, err: TextIO | None = None):
        self._jsonl = jsonl
        self._out = out
        self._err = err

    # Streams are looked up at write time: callers and test harnesses may replace sys.stdout/stderr
    # after the emitter was built, and a stale handle would raise "I/O operation on closed file".
    @property
    def _stdout(self) -> TextIO:
        return self._out or sys.stdout

    @property
    def _stderr(self) -> TextIO:
        return self._err or sys.stderr

    def event(self, name: str, human: str = "", **fields: Any) -> None:
        if human:
            print(human, file=self._stderr, flush=True)
        if self._jsonl:
            print(_dumps({"event": name, **fields}), file=self._stdout, flush=True)

    def result(self, data: Any = None, error: dict[str, str] | None = None) -> dict[str, Any]:
        envelope = {"ok": error is None, "data": data, "error": error}
        if self._jsonl:
            print(_dumps({"event": "result", **envelope}), file=self._stdout, flush=True)
        else:
            print(_dumps(envelope, indent=2), file=self._stdout, flush=True)
        return envelope


def _dumps(obj: Any, **kwargs: Any) -> str:
    # default=str: dates loaded from YAML are not JSON-native
    return json.dumps(obj, ensure_ascii=False, default=str, **kwargs)
