# hibor_cli_v1 — 给 agent 用的慧博研报抓取 CLI

一个独立的最小工具：用**你已登录的 Chrome**在慧博投研资讯（hibor.com.cn）上取研报，存成 Markdown，
再推进 WeKnora 知识库。它由 `hibor-web` 精简而来，只保留两条检索路径：

- **个股**（慧搜按名称/代码检索）
- **行业**（行业研报列表页按大类/细分行业浏览）

它抓的是站点正文**摘录**（详情页 `.abstruct-info`），不下载 PDF，不做品种归档，不带定时任务。

## 安装

推荐装成**系统级命令**（任意目录、任意终端里都能直接 `hibor …`，agent 也就能直接调）：

```powershell
uv tool install --from git+https://github.com/yingpcao/hibor_cli_v1.git hibor-cli
hibor init                                   # 写 ~/.hibor/config.yaml（可加 --profile-dir 复用已有登录）
hibor --version                              # hibor 1.1.0
```

装的是快照，改过代码要重装：`uv tool install --reinstall --from git+https://github.com/yingpcao/hibor_cli_v1.git hibor-cli`；
在本地仓库里开发就把 `--from` 换成目录（`uv tool install --reinstall --from C:\HiborAgent\hibor_cli_v1 hibor-cli`）。

`hibor init` 之后配置按 `--config` > `HIBOR_CONFIG` > `./config.yaml` > `~/.hibor/config.yaml` 找，
所以平时无需再传路径；配置文件里的相对路径以**该文件所在目录**为基准。想接着用本仓库已有的工作区与
登录态，就把 `output_dir`/`state_dir`/`profile_dir` 写成仓库里的绝对路径。

不需要 `playwright install`：本工具用系统 Chrome（`channel="chrome"`），只借它来持有登录态。

新克隆下来跑：`copy config.example.yaml config.yaml`（或干脆 `hibor init` 写 `~/.hibor/config.yaml`）。
`config.yaml` 里会放真实密钥，已在 `.gitignore` 里；WeKnora 密钥更建议只走环境变量 `WEKNORA_API_KEY`。

也可以在仓库里用独立 venv 跑（开发与测试用）：

```powershell
cd C:\HiborAgent\hibor_cli_v1
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt   # 只要运行则用 requirements.txt
.venv\Scripts\python.exe -m hibor_cli <命令>      # 与 hibor <命令> 等价；Windows 控制台 GBK 时先 set PYTHONIOENCODING=utf-8
```

## 登录（唯一需要人出面的步骤）

```powershell
hibor login
```

会打开一个 Chrome 窗口，登录慧博后**关闭该窗口**即可；会话就存在 `config.yaml` 里 `profile_dir`
指向的 Chrome 配置目录中。任何时候用 `doctor` 验证：

```powershell
hibor doctor
```

> 这个配置目录同一时刻只能被一个进程占用。hibor-web 的抓取任务和 v1 不能并行跑，
> 否则后启动的那个以退出码 6 结束（不会损坏登录态）。

> 实测（2026-10-04）：登录态失效时 `doctor` 报退出码 3，但列表与正文摘录仍抓得到 —— 站点这两处对该会话
> 是开放的。需要更完整的内容（下载、积分相关）时请先 `login`。

## 上手三条命令

```powershell
hibor stock list 紫金矿业 --days 30 --max 20   # 先看会处理哪些篇
hibor stock fetch 紫金矿业 --days 30 --max 20  # 再下载
hibor push --kb 投研资料 --stock 紫金          # 推知识库
```

stdout 永远只有一个 JSON 信封（`--jsonl` 时是事件流，末行是 result），人看的进度走 stderr：

输出统一是 **UTF-8 字节**（agent 直接按 UTF-8 解就好）。人自己在 cmd/PowerShell 里看时若出现乱码，
是当前控制台代码页为 936，先 `chcp 65001` 再跑；不要为此改代码。

PowerShell 5.1 里 `hibor … | ConvertFrom-Json` 会报「无效的 JSON」—— 它按 GBK 解码子进程字节，中文最后那个字节
会和后面的 `"` 拼成一个 GBK 字，引号被吞掉，**输出字节本身仍是合法 JSON**（cmd 重定向、Git Bash 管道都解析得开）。
解析前加一句即可：`[Console]::OutputEncoding=[Text.Encoding]::UTF8`。

```json
{
  "ok": true,
  "data": {"folder": "个股_紫金", "count": 12, "new": 12, "items": [{"id": "…", "title": "…", "already_saved": false, "relevance": "company"}]},
  "error": null
}
```

## 命令参考

| 命令 | 作用 |
| --- | --- |
| `init` | 写出配置模板（`~/.hibor/config.yaml`），系统级安装后的第一步，不需要已有配置 |
| `spec` | 输出机器可读的接口契约：命令、参数、默认值、退出码、信封结构（也不需要配置） |
| `stock list <名称>` | 列出该股会处理的报告，标注 `already_saved`，不下载 |
| `stock fetch <名称>` | 抓取并存为 Markdown |
| `industry list <行业>` / `industry fetch <行业>` | 同上，走行业列表页 |
| `status` | 各分组已保存/空正文/已过滤/失败的数量，`--failed` 附最近失败明细 |
| `push --kb 名称` | 把 output 下的分组上传到 WeKnora 知识库 |
| `doctor` | 检查 Profile 占用、登录态、是否被限流 |
| `industries` | 列出站点合法的行业大类与细分行业（`industry --sub` 用得上） |
| `login` | 打开浏览器手动登录 |

`hibor --version` 打印版本。除 `init`/`spec` 外所有命令都接受 `--config PATH`；不确定参数就
`hibor <命令> --help`，或直接读 `hibor spec`。

## 给 agent：spec 与技能包

- **`hibor spec`** 是接口契约的单一事实来源（`hibor_cli/spec.py`）。`tests/test_spec.py` 会拿它和
  argparse 真实的 `--help` 输出对账，所以改了参数忘了改文档会直接测试失败 —— agent 读到的不会过期。
- **`skills/hibor-reports/`** 是可分发的技能包，形状与 westock-data 一致：
  `SKILL.md`（触发条件、命令速查、硬约束、退出码处置）+ `references/{commands,routing-guide,troubleshooting}.md`
  + `scripts/setup.{ps1,sh,cjs}`。`tests/test_skill.py` 检查技能里出现的命令与参数都是真的。
- 安装 CLI 并把技能注册到 agent 主目录：

```powershell
powershell -ExecutionPolicy Bypass -File skills\hibor-reports\scripts\setup.ps1 -Skill
bash skills/hibor-reports/scripts/setup.sh --skill
node skills/hibor-reports/scripts/setup.cjs --skill
```

  脚本先确认 `hibor` 已在 PATH（没有就从本仓库装：`uv tool install --from <源码目录>`，或直接
  `uv tool install --from git+https://github.com/yingpcao/hibor_cli_v1.git hibor-cli`），`-Skill/--skill` 再把技能
  目录复制到**已存在**的 `~/.claude`、`~/.codex`、`~/.pi/agent` 下（对应 Claude Code / Codex / 本运行环境）。
  Qoder 用项目级目录：把技能包复制到 `<项目>/.qoder/skills/hibor-reports`。
  技能包已随仓库发布，所以社区的 `npx skills add yingpcao/hibor_cli_v1/hibor-reports` 也能直接装。

抓取范围参数（`list`/`fetch` 通用）：

- `--days N`：最近 N 天，默认 7。与 `--from YYYY-MM-DD [--to YYYY-MM-DD]` 互斥，后者优先。
- `--max N`：本次最多处理多少篇（默认 100），只统计真正入库/失败的，已保存和被过滤的不占名额。
- `--scope title|abstract|fulltext`（仅 `stock`）：关键词允许命中的位置，默认 `title`。
  `abstract` 就是慧搜网页上的「摘要」：命中点从标题换成站点给的正文摘录，召回更宽，
  因此第四道噪音闸会接手（见下一节）。
- `--keep-noise`（仅 `stock`）：关掉第四道噪音闸，用来确认「是不是被误滤了」。日常不需要。
- `--sub 细分行业`、`--keyword 标题词`（仅 `industry`）。
- `--jsonl`：输出事件流，适合逐行消费；`--config 路径`：换一份配置。

## 输出与状态

文件名直接用慧博自己的标题结构，只把开头的券商挪到末尾：

```
output/个股_紫金/紫金龙净-600388-海外矿山光储项目加速落地，电价机制打开盈利空间-260927_东吴证券.md
output/行业_有色金属/铜行业周报：COMEX铜库存创历史新高，中国铜社库创2024年2月以来新低-260927_光大证券.md
```

- 标题形如 `<券商>-<标的>-<代码>-<主题>-<研报日>`，重排后**打开目录先看到标的和主题**，券商只在需要区分时才用到；
- 不再加“分享时间（published）”前缀，也不带 source 页 ID —— 日期、ID、链接等一律在 frontmatter 里；
- 慧博标题末尾自带研报日期（`-260927`），所以文件名不另加日期字段；
- 代价是按名称排序时同一系列/同一标的相邻、不再按时间相邻（周报系列的几期会分散）；要时间序就看资源
  管理器的“修改时间”列，或读 frontmatter 的 `published`；
- 两个券商复用同一标题时，后保存的那篇会自动追加 `_报告ID前8位`，不会静默覆盖；
- 标题截到 80 字、券商段 24 字；Windows 非法字符（`\/:*?"<>|`）替换为 `_`。

一只股票、一个行业各占一个平铺目录（不按月分目录，慧博标题已带日期）。每篇开头是 frontmatter：
`title`、`stock:` 或 `industry:`（为什么抓它）、`subject`（站点点名的对象，如 `601899(紫金矿业)`）、
`relevance`（`company` 还是 `industry`）、`org`、`published`、`authors`、`rating`、`pages`、`source`。

去重靠 SQLite（`state/reports.db`，表 `report_items`，主键 `(报告ID, 分组)`）：
`done` 已保存、`empty` 无文字正文（图片型报告）、`filtered` 判定与本标的无关、`failed` 本次失败。
前三者重跑都不会再花一次详情页请求，`failed` 会自动重试。想强制重抓某篇，删掉它在库里的行即可。

## 个股检索的四道闸

慧搜是**分词模糊匹配**：搜“紫金”会连“华鑫期货…锡…有色”一起返回；用「摘要」命中时，还会连晨报、
行业周报、高频数据表一起返回。所以入库前判四道：

1. **标题闸**（列表期）：`--scope title` 时命中点就在标题，标题里必须真的连着出现该名称，否则丢弃；
2. **公司/行业二分**（列表期）：`subject` 形如 `601899(紫金矿业)` 的是 company，恒留 —— 站点已经点名了
   这只股票，所以它自己的《半年报点评》不会被第 3 道闸误伤；
3. **噪音闸**（列表期）：看站点的栏目面包屑（`行业分析→定期研报→行业周报`）和标题，滤掉“顺带提到”的：
   - **例行壳子，标题点了名也丢**：晨会早刊/晨会纪要/早间资讯、行业数据/数据周报/高频数据（Excel 底稿
     那一类）、期货日报/期货周报，以及标题里的「每日…晨报/导航/纵览」「周度观点」「日报」「一览表」——
     它们是把别人的研究拼起来或只摆数据的目录，不是冲着这家公司写的一篇；
   - **定期跟踪与点评，标题点了名就留**：`定期研报`/`定期策略` 栏目，以及以「点评/简评/快评」结尾的
     栏目或标题。摘要模式命中到它们通常是“本期覆盖名单里顺手列了这只”；而
     《环保行业跟踪周报：紫金龙净海外矿山光储项目加速落地》是冲着它写的，留着。
4. **正文闸**（详情期）：industry 类的正文摘录里必须提到该名称，否则丢弃。

第 4 道读的是摘录而非整份 PDF，所以会误杀少量确实相关的报告 —— 这是刻意的精度换召回。
被丢弃的条目会以 `filtered` 记录在状态库里（原因写在丢弃消息里），`list` 的结果里不会出现。

2026-10-04 实测：`stock list 紫金 --scope abstract --days 30` 命中 50 条，四道闸留 7 丢 43，留下的是一篇
站点点名的公司事件点评 + 同业深度/首次覆盖 + 两篇标题点了名的行业周报 + 一篇铜企专题报告。

摘要模式的标准用法：

```powershell
hibor stock list 紫金矿业 --scope abstract --days 30 --max 30   # 先看留下哪些、丢了哪些
hibor stock fetch 紫金矿业 --scope abstract --days 30 --max 30  # 认可再下载
```

觉得漏抓了就先加 `--keep-noise` 复查，别直接改规则：被误滤的条目会带着丢弃原因出现在 stderr（或
`--jsonl` 的 `filtered` 事件）里，对照栏目名和标题就能看出是哪一条规则命中的。

## 推送到 WeKnora

```powershell
hibor push --kb RP-小金属 --stock 紫金矿业 --dry-run
hibor push --kb 新库名 --create --industry 有色金属
```

- 不带 `--stock/--industry` 时遍历 `output` 下所有分组。
- 库名不存在会报错并在错误里列出可用的库；确认要新建才加 `--create`。
- 按**文件名**与库里已有条目比对，重复推送不会上传第二份（改了命名方案后老文件会被当作新文件再传一次）；
  上传后轮询 `parse_status` 直到 `completed`/`failed`，超过 `--timeout`（默认 600 秒）仍没解析完的算失败并列出。
- 地址读 `config.yaml`，**密钥读环境变量** `WEKNORA_API_KEY`（`WEKNORA_BASE_URL` 同样可覆盖），
  这样长期凭据不会进仓库。两者都缺就是 `config_error`。

## 退出码

| 码 | 含义 | 该怎么办 |
| --- | --- | --- |
| 0 | 成功 | — |
| 1 | 未预期的内部错误 | 看 stderr 的 traceback，报 issue |
| 2 | 用法/配置错误（含库名不存在、参数不合法） | 按 `error.message` 修命令 |
| 3 | 登录失效 | 跑 `hibor login` |
| 4 | 被限流/页面异常/连续失败 | 别再循环重试，隔一段时间再跑 |
| 5 | 跑完了，但有报告抓取失败 | 明细在 `data`，或 `status --failed` |
| 6 | Chrome 配置目录被占用 | 关掉别的抓取进程或登录窗口 |

`3/4/6` 也会带 `data`：中断前已经存下的篇数和文件路径都在里面。

## 风控与礼仪

站点前面是 safedog WAF。它对**已登录的自动化会话**限流时，会返回 HTTP 200 但正文完全空白 ——
程序把这种情况识别为 `blocked`（退出码 4）并立即停止，不重试。请保持这个行为：

- 不要调低 `config.yaml` 里的 `delay`，那是真实节奏而不是性能参数；
- 被限流时不要写循环重试，换时间再跑；
- 不要为了绕过验证去改 cookie（尤其别删 `safedog-flow-item`），也不要导出 cookie 给别的客户端用 ——
  Chrome 配置目录本身就是会话。
- 抓取内容仅供个人研究，请遵守网站用户协议。

