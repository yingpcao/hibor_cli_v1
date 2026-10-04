#!/usr/bin/env bash
# hibor 安装脚本（macOS / Linux，随技能包提供，可先审阅再执行）
#
# 用法:
#   bash setup.sh                       # 只装 CLI
#   bash setup.sh --skill               # 装 CLI 并把技能注册到已存在的 agent 主目录
#   bash setup.sh --source /path/to/hibor_cli_v1 --force --skill
#   bash setup.sh --dry-run | --help
#
# 参数:
#   --source DIR   hibor_cli_v1 源码目录（含 name = "hibor-cli" 的 pyproject.toml）。
#                  默认顺序：--source > $HIBOR_CLI_SOURCE > 技能包上两级目录
#   --skill        同时把本技能目录注册到已存在的 agent 主目录（~/.claude、~/.codex、~/.pi/agent）
#   --force        已装过也按当前源码重装
#   --bin-dir DIR  传给 uv 的 --bin-dir（默认 ~/.local/bin）
#   --dry-run      只打印将执行的命令
#   --yes          跳过确认
#   --help         显示帮助
#
# 说明：与 westock 的 setup 不同，这里没有远程二进制，所以不做 SHA256 固定校验 ——
# 装的是你本地（或你自己 clone）的源码，请先审阅源码再执行。
set -euo pipefail

SKILL_NAME="hibor-reports"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"

SOURCE="${HIBOR_CLI_SOURCE:-}"
BIN_DIR=""
WITH_SKILL=0
FORCE=0
DRY_RUN=0
ASSUME_YES=0

info() { echo "$@"; }
ok()   { echo "OK   $*"; }
warn() { echo "WARN $*" >&2; }
err()  { echo "ERR  $*" >&2; }

usage() { sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --source) SOURCE="${2:?--source 需要一个目录}"; shift 2 ;;
    --bin-dir) BIN_DIR="${2:?--bin-dir 需要一个目录}"; shift 2 ;;
    --skill) WITH_SKILL=1; shift ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) err "未知参数: $1（--help 看用法）"; exit 2 ;;
  esac
done

command -v uv >/dev/null 2>&1 || { err "找不到 uv。请先按 uv 官方文档安装 uv，再重跑本脚本 —— 本脚本不会替你装 uv。"; exit 1; }

is_source() {
  [ -n "$1" ] && [ -d "$1" ] && grep -Eq '^[[:space:]]*name[[:space:]]*=[[:space:]]*"hibor-cli"' "$1/pyproject.toml" 2>/dev/null
}

if is_source "$SOURCE"; then
  RESOLVED="$(cd "$SOURCE" && pwd)"
elif is_source "$(dirname "$(dirname "$SKILL_ROOT")")"; then
  RESOLVED="$(cd "$(dirname "$(dirname "$SKILL_ROOT")")" && pwd)"   # <repo>/skills/hibor-reports/scripts → <repo>
else
  err "没找到 hibor_cli_v1 源码目录（需含 name = \"hibor-cli\" 的 pyproject.toml）。"
  err "请用 --source 指定，或设环境变量 HIBOR_CLI_SOURCE；已发布到索引时可直接 uv tool install hibor-cli"
  exit 1
fi

info "源码: $RESOLVED"
info "CLI : hibor → ${BIN_DIR:-$HOME/.local/bin}"

if command -v hibor >/dev/null 2>&1 && [ "$FORCE" -eq 0 ]; then
  ok "hibor 已安装 → $(command -v hibor)：$(hibor --version)"
  info "  要按新源码重装请加 --force"
else
  [ "$DRY_RUN" -eq 1 ] || [ "$ASSUME_YES" -eq 1 ] || {
    printf '确认安装/重装 hibor? [Y/n] '
    read -r reply
    case "$reply" in [Nn]*) warn "已取消"; exit 0 ;; esac
  }
  install_args=(tool install --from "$RESOLVED")
  [ "$FORCE" -eq 1 ] && install_args+=(--reinstall)
  [ -n "$BIN_DIR" ] && install_args+=(--bin-dir "$BIN_DIR")
  if [ "$DRY_RUN" -eq 1 ]; then
    info "(dry-run) uv ${install_args[*]}"
  else
    uv "${install_args[@]}" || { err "uv tool install 失败"; exit 1; }
  fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
  [ "$WITH_SKILL" -eq 1 ] && info "(dry-run) 会把 $SKILL_ROOT 复制到各 agent 主目录下的 skills/$SKILL_NAME"
  info "(dry-run) 未做任何改动"
  exit 0
fi

command -v hibor >/dev/null 2>&1 || {
  warn "PATH 里还没有 hibor。重开终端，或把 ${BIN_DIR:-$HOME/.local/bin} 加进 PATH 后再试。"
  exit 1
}
ok "已安装 → $(command -v hibor)：$(hibor --version)"

if [ -f "$HOME/.hibor/config.yaml" ]; then
  info "配置已存在: $HOME/.hibor/config.yaml（要重来就 hibor init --force）"
else
  info "下一步：hibor init（写 ~/.hibor/config.yaml），然后 hibor login 让人工登录一次"
fi

if [ "$WITH_SKILL" -eq 1 ]; then
  count=0
  for home in "$HOME/.claude" "$HOME/.codex" "$HOME/.pi/agent"; do
    [ -d "$home" ] || { info "跳过（该 agent 未安装）: $home"; continue; }
    dest="$home/skills/$SKILL_NAME"
    mkdir -p "$(dirname "$dest")"
    rm -rf "$dest"
    cp -R "$SKILL_ROOT" "$dest"
    count=$((count + 1))
    ok "技能已注册 → $dest"
  done
  [ "$count" -eq 0 ] && warn "没有任何 agent 主目录存在，技能未注册。装好 Claude Code / Codex 后重跑本脚本加 --skill。"
  info "新会话里直接说「找某股的研报」或 /hibor-reports 即可命中。"
fi

ok "完成。自检：hibor spec（接口契约）、hibor doctor（登录/限流/Profile 状态）"
