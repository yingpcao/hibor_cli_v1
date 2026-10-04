#!/usr/bin/env node
// hibor 安装脚本（跨平台，Node ≥ 18，随技能包提供，可先审阅再执行）
//
// 用法:
//   node setup.cjs                      // 只装 CLI
//   node setup.cjs --skill              // 装 CLI 并把技能注册到已存在的 agent 主目录
//   node setup.cjs --source /path/to/hibor_cli_v1 --force --skill
//   node setup.cjs --dry-run | --help
//
// 参数与 setup.ps1 / setup.sh 一致：--source --bin-dir --skill --force --dry-run --yes --help
// 说明：这里没有远程二进制，所以不做 SHA256 固定校验 —— 装的是你本地（或你自己 clone）的源码。
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const SKILL_NAME = 'hibor-reports';
const SCRIPT_DIR = __dirname;
const SKILL_ROOT = path.dirname(SCRIPT_DIR);

const HELP = `用法: node setup.cjs [选项]
  --source DIR    hibor_cli_v1 源码目录（含 name = "hibor-cli" 的 pyproject.toml）
                  默认顺序：--source > 环境变量 HIBOR_CLI_SOURCE > 技能包上两级目录
  --bin-dir DIR   传给 uv 的 --bin-dir（默认 ~/.local/bin）
  --skill         同时把本技能目录注册到已存在的 agent 主目录（~/.claude、~/.codex、~/.pi/agent）
  --force         已装过也按当前源码重装
  --dry-run       只打印将执行的命令
  --yes           跳过确认
  --help          显示帮助`;

function parseArgs(argv) {
  const opts = { source: process.env.HIBOR_CLI_SOURCE || '', binDir: '', skill: false, force: false, dryRun: false, yes: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = () => {
      const value = argv[++i];
      if (value === undefined) throw new Error(`${arg} 需要一个值`);
      return value;
    };
    if (arg === '--source') opts.source = next();
    else if (arg === '--bin-dir') opts.binDir = next();
    else if (arg === '--skill') opts.skill = true;
    else if (arg === '--force') opts.force = true;
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--yes' || arg === '-y') opts.yes = true;
    else if (arg === '--help' || arg === '-h') { console.log(HELP); process.exit(0); }
    else throw new Error(`未知参数: ${arg}（--help 看用法）`);
  }
  return opts;
}

const info = (...a) => console.log(...a);
const ok = (m) => console.log(`OK   ${m}`);
const warn = (m) => console.error(`WARN ${m}`);
const bail = (m, code = 1) => { console.error(`ERR  ${m}`); process.exit(code); };

const run = (cmd, args) => spawnSync(cmd, args, { stdio: 'inherit', shell: false });
const quiet = (cmd, args) => spawnSync(cmd, args, { encoding: 'utf8', shell: false });

function which(name) {
  const probe = process.platform === 'win32' ? quiet('where', [name]) : quiet('sh', ['-c', `command -v ${name}`]);
  if (probe.status !== 0) return null;
  return (probe.stdout || '').split(/\r?\n/)[0].trim() || null;
}

function isSource(dir) {
  if (!dir) return false;
  try {
    return fs.existsSync(dir) && /^\s*name\s*=\s*"hibor-cli"/m.test(fs.readFileSync(path.join(dir, 'pyproject.toml'), 'utf8'));
  } catch {
    return false;
  }
}

let opts;
try {
  opts = parseArgs(process.argv.slice(2));
} catch (exc) {
  bail(`${exc.message}（--help 看用法）`, 2);
}

if (!which('uv')) bail('找不到 uv。请先按 uv 官方文档安装 uv，再重跑本脚本 —— 本脚本不会替你装 uv。');

const candidates = [opts.source, path.dirname(path.dirname(SKILL_ROOT))];  // 技能包在 <repo>/skills/hibor-reports/scripts 时上两级就是仓库根
const resolved = candidates.find(isSource);
if (!resolved) {
  bail('没找到 hibor_cli_v1 源码目录（需含 name = "hibor-cli" 的 pyproject.toml）。\n' +
       `试过: ${candidates.filter(Boolean).join('; ')}\n` +
       '请用 --source 指定，或设环境变量 HIBOR_CLI_SOURCE；已发布到索引时可直接 uv tool install hibor-cli');
}

const bindir = opts.binDir || path.join(os.homedir(), '.local', 'bin');
info(`源码: ${path.resolve(resolved)}`);
info(`CLI : hibor → ${bindir}`);

const already = which('hibor');
if (already && !opts.force) {
  const version = quiet('hibor', ['--version']).stdout?.trim() || '';
  ok(`hibor 已安装 → ${already}：${version}`);
  info('  要按新源码重装请加 --force');
} else {
  if (!opts.dryRun && !opts.yes && process.stdin.isTTY) {
    const answer = require('node:readline').questionSync('确认安装/重装 hibor? [Y/n] ');
    if (/^[Nn]/.test(answer)) { warn('已取消'); process.exit(0); }
  }
  const args = ['tool', 'install', '--from', path.resolve(resolved)];
  if (opts.force) args.push('--reinstall');
  if (opts.binDir) args.push('--bin-dir', opts.binDir);
  if (opts.dryRun) info(`(dry-run) uv ${args.join(' ')}`);
  else if (run('uv', args).status !== 0) bail('uv tool install 失败');
}

if (opts.dryRun) {
  if (opts.skill) info(`(dry-run) 会把 ${SKILL_ROOT} 复制到各 agent 主目录下的 skills/${SKILL_NAME}`);
  info('(dry-run) 未做任何改动');
  process.exit(0);
}

const installed = which('hibor');
if (!installed) {
  warn(`PATH 里还没有 hibor。重开终端，或把 ${bindir} 加进 PATH 后再试。`);
  process.exit(1);
}
ok(`已安装 → ${installed}：${quiet('hibor', ['--version']).stdout?.trim() || ''}`);

const userConfig = path.join(os.homedir(), '.hibor', 'config.yaml');
if (fs.existsSync(userConfig)) info(`配置已存在: ${userConfig}（要重来就 hibor init --force）`);
else info('下一步：hibor init（写 ~/.hibor/config.yaml），然后 hibor login 让人工登录一次');

if (opts.skill) {
  const homes = ['.claude', '.codex', path.join('.pi', 'agent')].map((rel) => path.join(os.homedir(), rel));
  let count = 0;
  for (const home of homes) {
    if (!fs.existsSync(home)) { info(`跳过（该 agent 未安装）: ${home}`); continue; }
    const dest = path.join(home, 'skills', SKILL_NAME);
    fs.rmSync(dest, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.cpSync(SKILL_ROOT, dest, { recursive: true });
    count++;
    ok(`技能已注册 → ${dest}`);
  }
  if (count === 0) warn('没有任何 agent 主目录存在，技能未注册。装好 Claude Code / Codex 后重跑本脚本加 --skill。');
  info('新会话里直接说「找某股的研报」或 /hibor-reports 即可命中。');
}

ok('完成。自检：hibor spec（接口契约）、hibor doctor（登录/限流/Profile 状态）');
