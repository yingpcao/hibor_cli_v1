# 故障排查

按 `error.code` 查。消息原文就是 CLI 打印的中文，可以据此匹配。

## 装不上 / 找不到命令

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| `hibor` 不是内部或外部命令 / `command not found` | 没装，或 `~/.local/bin` 不在 PATH | 跑技能包里的 `scripts/setup.ps1`（或 `.sh`/`.cjs`）；已装过则新开一个终端让 PATH 生效 |
| setup 脚本说找不到源码 | 技能是从别处复制来的，脚本找不到 `pyproject.toml` | 显式给源码目录：`setup.ps1 -Source C:\path\to\hibor_cli_v1` / `setup.sh --source /path/to/hibor_cli_v1`；或设环境变量 `HIBOR_CLI_SOURCE` |
| setup 脚本说没有 `uv` | 缺 uv | 先装 uv，再重跑脚本（脚本不会替你装 uv） |
| 改了代码但行为没变 | `uv tool install` 装的是快照 | `uv tool install --force <源码目录>` 重装，或 `uv tool upgrade hibor-cli` |

## 配置（`config_error`，退出码 2）

| 消息 | 含义 | 处置 |
| --- | --- | --- |
| `没找到配置（依次查过 …）。先运行 \`hibor init\` …` | 搜索顺序里一个配置都没有 | `hibor init`，或 `--config` 指一份现有配置 |
| `找不到配置文件: <path>` / `HIBOR_CONFIG 指向的文件不存在` | 显式路径写错 | 核对路径；注意相对路径是相对**配置文件所在目录**，不是当前目录 |
| `<path> 已存在；确认要覆盖再加 --force` | `init` 不想覆盖你的配置 | 要重来就加 `--force`（会丢掉你改过的节奏/路径设置），或直接把 `weknora.base_url` 之类单独编辑 |
| `config.yaml 含未知字段: ['xxx']` | 打错键名或塞了别的项目的键 | 合法键只有 `output_dir state_dir profile_dir headless delay max_consecutive_failures weknora` |
| `delay.detail 应为 [最小, 最大] 秒` / `需满足 0 <= 最小 <= 最大` | 节奏写反了或写了字符串 | 写成 `[3, 8]` 这种升序数组 |
| `缺少目标名称（个股名或行业名）` | 位置参数为空 | 补上名称；名称里有空格要加引号 |
| `行业抓取走行业列表页，没有 --scope 概念` | 给 `industry` 传了 `--scope` | 去掉它 |
| `date_range 结束早于开始` / `日期格式应为 YYYY-MM-DD` | `--from/--to` 写错 | 用 `YYYY-MM-DD`，或改用 `--days` |
| `未配置 WeKnora：请在 config.yaml 的 weknora 段填写 base_url 与 api_key…` | 地址或密钥缺失 | 密钥用环境变量 `WEKNORA_API_KEY`（别写进文件再分享目录）；地址 `WEKNORA_BASE_URL` 或配置文件 |
| `分组目录不存在: [...]；已抓取的分组: [...]` | `push --stock/--industry` 的名字没对上 | 用错误里列出的分组名，或先 `hibor status` |
| `<output_dir> 下没有已抓取的分组，先运行 fetch` | 还没抓过 | 先 `fetch` |
| `知识库 'X' 不存在，可用: [...]` | 库名写错 | 从错误列出的库里选；确认要新建才加 `--create` |

## 登录与风控

| code / 消息 | 含义 | 处置 |
| --- | --- | --- |
| `login_required` · `未登录，请运行 \`hibor login\`` | doctor 在页面里没找到「退出登录」 | **人工**登录（agent 不要静默跑 `login`）。但注意：列表页与正文摘录对未登录会话通常仍开放，`list` 能跑就别拦着用户 |
| `login_required` · `跳转到登录页: <url>` / `页面要求登录: <url>` | 抓取途中会话失效 | 同上，请用户重新登录；已存下的篇数在 `data` 里 |
| `blocked` · `行业页返回空白页，疑似被限流，稍后再试` | safedog WAF 用 HTTP 200 + 空白页回你 | **立即停止，不要重试循环**。隔一段时间（至少几十分钟）再跑；不要调低 `delay`、不要删 `safedog-flow-item` cookie、不要导出 cookie |
| `blocked` · `连续失败 N 次，停止（可能被风控）` | 同一原因，跑中途触发 | 同上 |
| `blocked` · `正文容器未出现（可能被风控/积分不足/页面异常）` | 这篇的详情页没给摘录 | 可能是积分/额度不足（需登录），也可能页面改版。别对整个任务重试；`status --failed` 看是哪几篇 |
| `blocked` · `慧搜返回内容缺少 hidTotal（可能登录失效或被风控）` | 慧搜响应不是预期结构 | 先 `doctor` 分清是限流还是登录问题 |
| `blocked` · `慧搜接口返回 <非200>` | 接口异常 | 停手，告知用户 |
| `profile_busy` · `Chrome 配置目录正被另一个进程使用: <dir>` | profile 同一时刻只能一个进程持有（`hibor-web` 的任务也算） | 找出占用者请用户关闭；**不要擅自 kill 进程**；登录状态本身不会丢 |
| `empty_content` · `无文字正文（可能是图片型报告）`（只在 `data.empty`/事件流里出现，不是退出码） | 扫描版/图片型研报 | 如实说明这篇没有文字正文 |

## WeKnora（`push`）

| code | 含义 | 处置 |
| --- | --- | --- |
| `weknora_unauthorized` | 密钥无效/过期（401/403） | 换 `WEKNORA_API_KEY`，别把密钥写进配置文件 |
| `weknora_unreachable` | 服务地址连不上 | 检查 `weknora.base_url` / 网络；这条退出码是 4，不要当成被慧博限流 |
| `weknora_bad_request` · `WeKnora 在 <path> 返回失败: <message>` | 接口拒绝（格式/参数） | 转述 message 给用户 |
| 退出码 5 + `N 篇上传或解析未成功` | 跑完了但有篇目失败/超时 | 明细在 `data.failed`；解析超过 `--timeout`（默认 600s）也算失败，可单独重推那一组 |

## 输出看着不对

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 中文变成乱码/`????` | Windows 控制台 GBK，且是解释器直跑（`python -m hibor_cli`） | 用 `hibor` 命令（它自己会把 stdout/stderr 设成 UTF-8），或先 `set PYTHONIOENCODING=utf-8` |
| PowerShell 里 `ConvertFrom-Json` 报「无效的 JSON 基元/缺少结束引号」 | PS 5.1 用 GBK 解码子进程字节，中文最后一个字节会和后面的 `"` 拼成一个 GBK 字，引号被吞 —— 字节本身是合法 UTF-8 | 解析前先 `[Console]::OutputEncoding=[Text.Encoding]::UTF8`；或改用 cmd 重定向到文件再按 UTF-8 读；别改 CLI 的编码 |
| 结果里少了很多篇 | 四道闸丢弃了它们 | stderr 的 `~~ 丢弃 <标题>: <原因>`，或 `--jsonl` 的 `filtered` 事件；怀疑误杀就加 `--keep-noise` 复查，**不要改 `relevance.py`** |
| 命中的都不是这只股票 | 慧搜是分词匹配，简称容易被切开 | 换全称或 6 位代码；别用 `--scope abstract` 当万能药（命中点变成正文摘录，噪音更多） |
| `count` 有数但 `new: 0` | 这些篇早就抓过了（去重在 SQLite） | 正常；要重抓就删库里对应行 |
| `--max` 好像没生效 | `already_saved` 与被过滤的不占名额 | 这是设计：`--max` 限的是真正要处理的篇数 |
| stdout 解析失败（多行/带进度） | 抓错了流 | 进度与丢弃原因在 **stderr**；stdout 只有一个 JSON 信封（`--jsonl` 时每行一个事件，末行 `result`） |
