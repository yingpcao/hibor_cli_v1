# hibor 命令完整参考

与 `hibor spec` 的输出同源（`hibor_cli/spec.py`，由 `tests/test_spec.py` 与真实 `--help` 对账）。
需要机器可读版本时直接跑 `hibor spec`，别手抄本文。

全局：`hibor --version`；除 `init`/`spec` 外的命令都接受 `--config PATH`。

---

## hibor init

写出配置模板。系统级安装后的第一步，**不需要已有配置**。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--path PATH` | `~/.hibor/config.yaml` | 写到哪儿 |
| `--profile-dir PATH` | `<配置目录>/chrome-profile` | Chrome 配置目录。想复用已有登录（例如仓库里跑过的那份 profile），把它的绝对路径填在这里 |
| `--force` | — | 覆盖已存在的配置；不加而文件已存在时退出码 2 |

返回 `data`：`{config, profile_dir, next}`。模板里的 `weknora.api_key` 是空串，密钥走环境变量。

## hibor spec

输出接口契约：命令、flag、默认值、退出码、信封结构、四道闸、硬约束。**不需要配置也能跑**。

返回 `data`：`{name, install, envelope, config, exit_codes, commands, relevance_gates, conventions,
version, config_path}`。没有可用配置时 `config_path` 为 `null`，并附 `config_error` 说明去哪找、
以及建议先跑 `hibor init`。

## hibor stock list / fetch

个股研报，走慧博的慧搜（分词模糊匹配）。`list` 只列会处理哪些篇、不下载；`fetch` 抓成 Markdown。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `name` | 必填（位置参数） | 个股简称或代码，如 `紫金` / `601899`。简称有歧义时先用全称或代码 `list` 一次 |
| `--scope title\|abstract\|fulltext` | `title` | 关键词允许命中的位置。`abstract` 即慧搜网页上的「摘要」：命中点从标题变成站点给的正文摘录，召回更宽、噪音更多，由噪音闸接手 |
| `--keep-noise` | off | 关掉第四道噪音闸，只在排查漏抓时用 |
| `--days N` | 7 | 最近 N 天 |
| `--from YYYY-MM-DD` / `--to YYYY-MM-DD` | — | 明确日期区间，优先于 `--days` |
| `--max N` | 100 | 最多处理多少篇；`already_saved` 与被过滤的不占名额 |
| `--jsonl` | — | stdout 改事件流，每行一个事件，末行 `result` |
| `--config PATH` | 搜索顺序 | 换一份配置 |

`list` 的 `data`：

```json
{"folder": "个股_紫金", "count": 2, "new": 0,
 "items": [{"id": "…", "url": "…", "title": "…", "published": "2026-09-27", "org": "东吴证券",
            "column": "公司调研→公司评论→事件点评", "authors": "…", "rating": "", "pages": "共3页",
            "subject": "600388(紫金龙净)", "already_saved": true, "relevance": "company"}]}
```

`fetch` 的 `data`：`{folder, saved, skipped, empty, failed, filtered, saved_paths}`。

- 被丢弃的条目不在 `items` 里，原因以 `~~ 丢弃 <标题>: <原因>` 走 stderr（`--jsonl` 时是 `filtered` 事件），
  并存进状态库；
- `list` 不写文件，也不消耗 `fetch` 的额度，适合先探再抓；
- 去重键是 `(报告ID, 分组)`，`done`/`empty`/`filtered` 不再花详情页请求，`failed` 会重试。

## hibor industry list / fetch

行业研报，走行业列表页（不是慧搜）。参数与 `stock` 相同的窗口控制（`--days`/`--from`/`--to`/`--max`/
`--jsonl`/`--config`），差异：

| 参数 | 说明 |
| --- | --- |
| `name` | 一级行业名，取值必须来自 `hibor industries` |
| `--sub 细分行业` | 同样以 `hibor industries` 的输出为准 |
| `--keyword 标题词` | 站点侧标题过滤 |

没有 `--scope`（不走慧搜），四道闸也不干预。行业页没有服务端日期过滤，CLI 按分享时间倒序翻到超出范围为止。
`data` 结构与 `stock` 一致，分组名形如 `行业_有色金属`。

## hibor status

查已抓取状态。**不联网、不开浏览器**，所以随时可查、可与其他命令并行。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--folder NAME` | — | 只看某个分组，如 `个股_紫金` |
| `--failed` | off | 附带最近失败明细 |
| `--limit N` | 20 | 失败明细条数 |

返回 `data`：`{config_path, folders: [{folder, done, empty, failed, filtered}], failed: [...]}`。

## hibor push

把 `output` 下的分组上传到 WeKnora 知识库。**不碰慧博、不开浏览器**，但会写共享库 —— 先 `--dry-run`。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--kb NAME_OR_ID` | 必填 | 知识库名称或 ID；名称不存在会报错并在错误里列出可用库 |
| `--stock NAME…` | — | 推送 `个股_<NAME>` 分组（可多个） |
| `--industry NAME…` | — | 推送 `行业_<NAME>` 分组（可多个） |
| `--create` | off | 库不存在时按名称新建（只在用户确认后才加） |
| `--description TEXT` | — | 配合 `--create` 的新库描述 |
| `--dry-run` | off | 只列出会上传哪些篇 |
| `--timeout SEC` | 600 | 等待解析完成的秒数上限 |
| `--jsonl` / `--config` | — | 同前 |

返回 `data`：`{kb: {id,name}, dry_run, uploaded, completed, already_in_kb, failed, folders}`；
`failed` 非空时退出码 5。按**文件名**与库里条目比对，改了文件名会被当新文件重传。
地址读 `config.yaml` 的 `weknora.base_url`，密钥读环境变量 `WEKNORA_API_KEY`
（`WEKNORA_BASE_URL` 可覆盖地址），两者都缺就是 `config_error`。

## hibor doctor

体检：profile 占用、登录态、是否被限流。**会开真实浏览器**。

返回 `data`：`{config_path, profile_dir, profile_busy, logged_in, blocked}`。
profile 被占 → 码 6 且不开浏览器；空白页 → 码 4；未登录 → 码 3（但列表页与正文摘录对未登录会话仍开放）。

## hibor industries

列出站点合法的行业大类与细分行业，返回 `data.industries: [{name, sub_industries: [...]}]`。
`industry --sub` 的取值来源；不确定行业名时先跑它，别猜。

## hibor login

打开 Chrome 让人工登录一次，会话留在 profile 目录。返回 `data: {profile, saved: true}`。

**唯一需要人出面的命令**：agent 不要自己静默跑，请用户执行，或在用户明确同意后再执行。

---

## 配置

搜索顺序：`--config` > `HIBOR_CONFIG` > `./config.yaml` > `~/.hibor/config.yaml`。
配置文件里的相对路径都以**该文件所在目录**为基准，所以 `~/.hibor/config.yaml` 是自包含的一套工作区
（`~/.hibor/output`、`~/.hibor/state`、`~/.hibor/chrome-profile`）；想让系统级命令接着用仓库里已有的
工作区和登录态，就把这三项写成仓库的绝对路径。

环境变量：`HIBOR_CONFIG`（配置路径）、`HIBOR_PROFILE_DIR`（覆盖 profile_dir）、
`WEKNORA_BASE_URL`、`WEKNORA_API_KEY`。

键：`output_dir`、`state_dir`、`profile_dir`、`headless`、`delay{detail,page,batch_size,batch_pause}`、
`max_consecutive_failures`、`weknora{base_url,api_key}`。出现未知键直接是配置错误（不会静默忽略）。
