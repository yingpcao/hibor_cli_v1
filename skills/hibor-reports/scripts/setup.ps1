# hibor 安装脚本（Windows PowerShell，随技能包提供，可先审阅再执行）
#
# 用法:
#   .\setup.ps1 -Skill                                   # 装 CLI，并把技能复制进各 agent 的技能目录
#   .\setup.ps1 -Source "C:\HiborAgent\hibor_cli_v1" -Force -Skill
#   .\setup.ps1 -DryRun / .\setup.ps1 -Help
#
# 参数（全部可选）:
#   -Source  hibor_cli_v1 源码目录（含 name = "hibor-cli" 的 pyproject.toml）。
#            默认按顺序找：-Source > 环境变量 HIBOR_CLI_SOURCE > 技能包上两级目录（随源码分发时）
#   -Skill   同时把本技能目录注册到已存在的 agent 主目录（~\.claude、~\.codex、~\.pi\agent）
#   -Force   已装过也按当前源码重装（改完代码更新 CLI 用）
#   -Bindir  传给 uv 的 --bin-dir（默认 uv 自己的 ~/.local/bin）
#   -DryRun  只打印将执行的命令，不改动任何东西
#   -Yes     跳过确认
#   -Help    显示帮助
#
# 说明：与 westock 的 setup 不同，这里没有远程二进制，所以不做 SHA256 固定校验 ——
# 装的是你本地（或你自己 clone）的源码，请先审阅源码再执行。
[CmdletBinding()]
param(
  [string]$Source = "",
  [string]$Bindir = "",
  [switch]$Skill,
  [switch]$Force,
  [switch]$DryRun,
  [switch]$Yes,
  [switch]$Help
)

$ErrorActionPreference = "Stop"

$SkillName = "hibor-reports"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptDir

function Write-Info  { Write-Host $args }
function Write-Green { param([string]$Msg) Write-Host "OK   $Msg" -ForegroundColor Green }
function Write-Warn  { param([string]$Msg) Write-Host "WARN $Msg" -ForegroundColor Yellow }
function Write-Err   { param([string]$Msg) Write-Host "ERR  $Msg" -ForegroundColor Red }

if ($Help) { Get-Help $MyInvocation.MyCommand.Path; exit 0 }

# ---- uv 是硬依赖：本工具是 Python 包，靠 uv tool 装成独立命令 ----
if ($null -eq (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Err "找不到 uv。请先按 uv 官方文档安装 uv，再重跑本脚本 —— 本脚本不会替你装 uv。"
  exit 1
}

# ---- 源码目录解析 ----
function Test-Source([string]$dir) {
  if ([string]::IsNullOrEmpty($dir) -or -not (Test-Path $dir)) { return $false }
  $pyproject = Join-Path $dir "pyproject.toml"
  return (Test-Path $pyproject) -and ((Get-Content $pyproject -Raw) -match '(?m)^\s*name\s*=\s*"hibor-cli"')
}

$candidates = @()
if (-not [string]::IsNullOrEmpty($Source)) { $candidates += $Source }
if ($env:HIBOR_CLI_SOURCE) { $candidates += $env:HIBOR_CLI_SOURCE }
# 技能包在 <repo>/skills/hibor-reports/scripts 时，仓库根就是上两级
$candidates += (Split-Path -Parent (Split-Path -Parent $SkillRoot))
$resolved = $null
foreach ($c in $candidates) { if (Test-Source $c) { $resolved = (Resolve-Path $c).Path; break } }

if ($null -eq $resolved) {
  Write-Err "没找到 hibor_cli_v1 源码目录（需含 name = ""hibor-cli"" 的 pyproject.toml）。"
  Write-Err "试过: $($candidates -join '; ')"
  Write-Err "请用 -Source 指定，或设环境变量 HIBOR_CLI_SOURCE；已发布到索引时可直接 uv tool install hibor-cli"
  exit 1
}

Write-Info "源码: $resolved"
Write-Info "CLI : hibor → $(if ($Bindir) { $Bindir } else { "$env:USERPROFILE\.local\bin" })"

$already = Get-Command hibor -ErrorAction SilentlyContinue
if ($already -and -not $Force) {
  Write-Green "hibor 已安装 → $($already.Source)：$((hibor --version) -join ' ')"
  Write-Info "  要按新源码重装请加 -Force"
} else {
  if (-not $Yes) {
    $reply = Read-Host "确认安装/重装 hibor? [Y/n]"
    if ($reply -match '^[Nn]$') { Write-Warn "已取消"; exit 0 }
  }
  $installArgs = @("tool", "install", "--from", $resolved)
  if ($Force) { $installArgs += "--reinstall" }
  if ($Bindir) { $installArgs += @("--bin-dir", $Bindir) }
  if ($DryRun) {
    Write-Info "(dry-run) uv $($installArgs -join ' ')"
  } else {
    & uv @installArgs
    if ($LASTEXITCODE -ne 0) { Write-Err "uv tool install 失败（退出码 $LASTEXITCODE）"; exit 1 }
  }
}

if ($DryRun) {
  if ($Skill) { Write-Info "(dry-run) 会把 $SkillRoot 复制到各 agent 主目录下的 skills\$SkillName" }
  Write-Info "(dry-run) 未做任何改动"
  exit 0
}

# ---- 验证 ----
$refreshed = Get-Command hibor -ErrorAction SilentlyContinue
if ($null -eq $refreshed) {
  Write-Warn "PATH 里还没有 hibor。重开终端，或把 $(if ($Bindir) { $Bindir } else { "$env:USERPROFILE\.local\bin" }) 加进 PATH 后再试。"
  exit 1
}
Write-Green "已安装 → $($refreshed.Source)：$((hibor --version) -join ' ')"

# ---- 首次配置 ----
$userConfig = Join-Path $env:USERPROFILE ".hibor\config.yaml"
if (Test-Path $userConfig) {
  Write-Info "配置已存在: $userConfig（要重来就 hibor init --force）"
} else {
  Write-Info "下一步：hibor init（写 $userConfig），然后 hibor login 让人工登录一次"
}

# ---- 技能注册 ----
if ($Skill) {
  # Qoder 用项目级目录（<repo>\.qoder\skills），不在用户级重复注册，免得同名技能出现两份
  $homes = @("$env:USERPROFILE\.claude", "$env:USERPROFILE\.codex", "$env:USERPROFILE\.pi\agent")
  $count = 0
  foreach ($h in $homes) {
    if (-not (Test-Path $h)) { Write-Info "跳过（该 agent 未安装）: $h"; continue }
    $dest = Join-Path (Join-Path $h "skills") $SkillName
    if (-not (Test-Path (Split-Path -Parent $dest))) { New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null }
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse -Force $SkillRoot $dest
    $count++
    Write-Green "技能已注册 → $dest"
  }
  if ($count -eq 0) { Write-Warn "没有任何 agent 主目录存在，技能未注册。装好 Claude Code / Codex 后重跑本脚本加 -Skill。" }
  Write-Info "新会话里直接说「找某股的研报」或 /hibor-reports 即可命中。"
}

Write-Green "完成。自检：hibor spec（接口契约）、hibor doctor（登录/限流/Profile 状态）"
