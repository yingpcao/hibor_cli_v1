---
name: hibor-reports
description: 慧博投研资讯（hibor.com.cn）研报检索与抓取的权威入口。用 `hibor` 命令按个股/行业慧搜研报、抓取正文摘录成 Markdown、推送到 WeKnora 知识库，并正确处置登录失效（3）、WAF 限流（4）、Chrome Profile 占用（6）等退出码。当用户要找某只股票或行业的研报、更新研报、批量入库、推知识库、问抓取状态，或提到 hibor/慧博/慧搜/研报摘要/WeKnora 时使用。只抓站点正文摘录，不下载 PDF；行情与财务数字走 westock-data，不用本技能凑。
version: 1.1.0
---

# 慧博研报抓取（hibor CLI）

## 安装

`hibor` 是系统级命令（uv tool 装的），任意目录都能跑。**首次使用前先确认它存在**：

```powershell
hibor --version          # 找不到命令时跑本技能自带的安装脚本
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Skill   # Windows
bash scripts/setup.sh --skill                                        # macOS / Linux
node scripts/setup.cjs --skill                                       # 跨平台（需 Node ≥ 18）
```

安装脚本只做两件事：`uv tool install <源码目录>` 装出 `hibor`，以及 `-Skill` 把本目录复制到
`~/.claude/skills/`、`~/.codex/skills/`。装好后：

```powershell
hibor init      # 写 ~/.hibor/config.yaml（可加 --profile-dir 复用已有的 Chrome 登录）
hibor login     # 唯一需要人出面的步骤：开浏览器登录一次，会话存在 profile 里
hibor doctor    # 体检：profile 占用 / 登录态 / 是否被限流
```

`hibor` 找不到配置时按 `--config` > `HIBOR_CONFIG` > `./config.yaml` > `~/.hibor/config.yaml` 搜索，
所以 agent 通常什么都不用传；配置缺失会以退出码 2 报「先运行 hibor init」。

---

**调用方式**：`hibor <命令> [参数]`，需要网络和一个已登录的 Chrome profile。

**不确定参数时**：`hibor spec` 输出机器可读的完整契约（命令、flag、默认值、退出码、信封结构），
`hibor <命令> --help` 输出单条命令的说明。**不要凭猜拼参数**，也不要在 `spec` 之外反复试跑抓取命令。

**并发**：`status`、`push`、`spec` 不开浏览器，可与其他命令并行；`stock|industry list|fetch`、`doctor`、
`industries`、`login` 共用一个 Chrome profile，**同一时刻只能有一个在跑**，第二个直接退出码 6。

---

## 命令速查

| 意图 | 命令 |
| --- | --- |
| 看个股会处理哪些篇（不下载） | `hibor stock list 紫金 --days 30 --max 20` |
| 抓个股并存 Markdown | `hibor stock fetch 紫金 --days 30 --max 20` |
| 简称/代码召不回，改按「摘要」检索 | `hibor stock list 紫金 --scope abstract --days 30` |
| 看行业会处理哪些篇 | `hibor industry list 有色金属 --sub 工业金属 --days 14` |
| 抓行业 | `hibor industry fetch 有色金属 --days 14` |
| 合法的行业/细分行业名 | `hibor industries` |
| 已抓取状态、失败明细 | `hibor status` / `hibor status --failed` |
| 推 WeKnora（先看再推） | `hibor push --kb 库名 --stock 紫金 --dry-run` → 去掉 `--dry-run` |
| 体检 / 接口契约 / 版本 | `hibor doctor` / `hibor spec` / `hibor --version` |

`list` 与 `fetch` 共用范围参数：`--days N`（默认 7）与 `--from/--to`（优先）；`--max N`（默认 100，
已保存与被过滤的不占名额）；`--jsonl` 事件流；`--config PATH`。个股另有 `--scope title|abstract|fulltext`
（默认 title）与 `--keep-noise`；行业另有 `--sub`、`--keyword`。完整参数与返回字段见
[commands.md](./references/commands.md)。

## 核心铁律

1. **标准流程是 list → fetch → push**。名称有歧义、日期范围未知、或用户只说"找点某股的研报"时，
   先 `list`（不写文件、不占额度），确认命中篇数与标题再 `fetch`。
2. **`push` 是写共享知识库的操作**：先 `--dry-run` 列出会上传哪些篇，并向用户确认后才真推。
3. **退出码 3/4/6 之后不要写循环重试**：3 要人工 `hibor login`（agent 不要自己跑，交给用户），
   4 是被 WAF 限流（隔一段时间再跑），6 是先找出占用 profile 的进程并请用户关闭 —— 不要擅自 kill 进程。
4. **非零退出也常带 `data`**：中断前已存下的篇数与 `saved_paths` 都在里面，先读它再决定怎么补跑。
5. **抓的是详情页文字摘录，不是整份 PDF**。回答用户时**禁止**说成「全文已入库」；图片型报告会记成 `empty`。
6. **不要为了"跑得快"改配置**：不要调低 `delay`，不要删 `safedog-flow-item` cookie，不要把 cookie 导出给
   别的客户端。被限流时不要换参数硬打。
7. **不要改 `hibor_cli/relevance.py` 的规则表**来"多抓点"。怀疑漏抓就加 `--keep-noise` 复查，
   stderr 的「丢弃 xxx: 原因」会写明命中的是哪条规则。
8. stdout 只有一个 JSON 信封，进度与丢弃原因走 stderr；**别用 `| head`/`| grep` 截断输出**，
   条数用 `--max`、`status --limit` 这类命令自身的参数控制。
9. **PowerShell 里解析 JSON 前先切 UTF-8**：`[Console]::OutputEncoding=[Text.Encoding]::UTF8`。
   PowerShell 5.1 默认按 GBK 解码子进程字节，中文尾部的字节会连带吞掉右引号，`ConvertFrom-Json` 直接报
   「无效的 JSON」——这不是 CLI 的错，输出字节本身是合法 UTF-8（cmd 重定向、Git Bash 管道都能正常解析）。

## 个股相关性四道闸

慧搜是分词模糊匹配：搜「紫金」会连"锡…有色"一起返回；用「摘要」命中时还会连晨报、行业周报、
高频数据表一起返回。CLI 在入库前自动判四道，被丢弃的条目以 `filtered` 记进状态库、不出现在 `items` 里：

| 闸 | 时机 | 规则 |
| --- | --- | --- |
| 标题闸 | 列表期 | `--scope title` 时标题必须连着出现该名称，否则丢弃 |
| 公司/行业二分 | 列表期 | `subject` 形如 `601899(紫金矿业)` 判 company **恒留**（站点已点名，它的《半年报点评》不会被误伤） |
| 噪音闸 | 列表期 | 晨会/早间资讯/行业数据/高频数据/日报周报这类例行壳子**标题点了名也丢**；`定期研报`/`定期策略`/「点评·简评·快评」只在**标题未点名本股**时丢 |
| 正文闸 | 详情期 | industry 类的正文摘录必须提到该名称，否则丢弃（刻意用精度换召回） |

`--scope abstract` 的召回明显更宽，所以**默认用 title**；只有 title 模式召不回用户要的报告时才升级，
并且先 `list` 看 stderr 的丢弃原因、确认没误杀，再 `fetch`。`industry` 不走慧搜，四道闸不干预它。

## 读结果与退出码

信封：`{"ok": bool, "data": {...}|null, "error": {"code","message"}|null}`。

| 码 | 含义 | 处置 |
| --- | --- | --- |
| 0 | 成功 | 读 `data.folder`、`count/new` 或 `saved/filtered/failed`，把 `output/<分组>/` 报给用户 |
| 1 | 内部错误 | 看 stderr traceback，别重复试 |
| 2 | 用法/配置错误（含没配置、库名不存在） | 按 `error.message` 改命令；缺配置就 `hibor init` |
| 3 | 登录失效 | 告知用户跑 `hibor login`；**抓取本身可能仍能跑**，见下 |
| 4 | 被限流/页面异常/连续失败 | 立即停止，不重试，告知用户稍后再跑 |
| 5 | 跑完但有失败篇 | `hibor status --failed` 取明细，只报失败项 |
| 6 | Chrome profile 被占用 | 找出占用者（另一个抓取进程/登录窗口）请用户处理 |

> `doctor` 报 `logged_in: false`（码 3）**不代表抓不到**：列表页与正文摘录对未登录会话是开放的，
> 照常 `list`；只有额度/全文类需求才要求用户登录。

## 输出与状态

- 文件在 `output/个股_<名称>/<标的>-<代码>-<主题>-<日期>_<券商>.md`，或 `output/行业_<名称>/…`；
  frontmatter 里有 `title`、`stock`/`industry`、`subject`、`relevance`、`org`、`published`、`source` 等。
- 去重在 SQLite（`state/reports.db`，主键 报告ID+分组）：`done`/`empty`/`filtered` 不再花详情页请求，
  `failed` 自动重试。要强制重抓某篇就删掉它在库里的行。
- `push` 按**文件名**与库里条目比对：改了文件名会被当新文件重传。

## 异常与空结果

1. 命令失败就如实转述 `error.message`，**禁止**编造报告标题或篇数。
2. `count: 0` 要区分：日期窗口太窄（放大 `--days`）、名称不对（换代码或全称）、还是站点确实没有。
3. 需要 PDF 原文、公告、实时行情/财务数字 —— 本技能做不到，如实告知并指向合适的工具。

细节见 [troubleshooting.md](./references/troubleshooting.md)；与 westock-data / WeKnora 的分工见
[routing-guide.md](./references/routing-guide.md)。

---

## 重要声明

抓取的正文摘录仅供个人研究，请遵守慧博投研资讯的用户协议；输出是站点的文字摘录而非整份研报，
不构成投资建议。
