"""Data passed between modules + the expected failures and their stable codes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ReportMeta:
    id: str
    url: str
    title: str
    published: str  # "YYYY-MM-DD HH:MM:SS" on the industry list, "YYYY-MM-DD" on 慧搜
    org: str
    column: str
    authors: str
    rating: str
    pages: str
    # 慧搜列表第 2 列：个股报告是 `002516(旷达科技)`，行业报告是 `(钢铁供应链行业)`；行业列表页没有这一列。
    subject: str = ""


class HiborError(Exception):
    """Expected failure. `code` is the machine-readable identifier the CLI maps to an exit code.
    `partial` carries what a fetch had already saved before it aborted (set by crawl.fetch_target)."""

    code = "error"
    partial: object | None = None


class ConfigError(HiborError):
    code = "config_error"


class ProfileBusyError(HiborError):
    """The persistent Chrome profile is already open in another process."""

    code = "profile_busy"


class EmptyContentError(HiborError):
    """The page is fine but has no text body (image-only report). Skip it, don't abort the run."""

    code = "empty_content"


class SessionError(HiborError):
    """Stop the whole run: the site is not serving us normally."""

    code = "session"


class LoginRequiredError(SessionError):
    """Redirected to the login page or shown the login layer: run `hibor login`."""

    code = "login_required"


class BlockedError(SessionError):
    """Blank or unexpected pages, missing containers, repeated failures: likely WAF, quota or risk control."""

    code = "blocked"


class WeKnoraError(HiborError):
    """WeKnora rejected the request with something we cannot fix from here."""

    code = "weknora_bad_request"


class WeKnoraUnauthorizedError(WeKnoraError):
    """401/403: wrong API key, or no access to that knowledge base."""

    code = "weknora_unauthorized"


class WeKnoraUnreachableError(WeKnoraError):
    """Connection, TLS, timeout or 5xx: the server did not answer normally."""

    code = "weknora_unreachable"
