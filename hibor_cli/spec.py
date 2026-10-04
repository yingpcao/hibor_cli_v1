"""`hibor spec` 的内容：给 agent 读的接口契约。

这里刻意只放**事实**（命令、参数、默认值、退出码、返回结构、硬约束），不放教程；教程在 README 与
技能包的 references/。`tests/test_spec.py` 会把这份表和 `hibor <命令> --help` 的实际输出对账，
所以改了 argparse 忘了改这里会直接测试失败 —— 契约不会悄悄过期。
"""

EXIT_CODES = {"ok": 0, "internal": 1, "config_error": 2, "weknora_bad_request": 2, "login_required": 3,
              "weknora_unauthorized": 3, "blocked": 4, "session": 4, "weknora_unreachable": 4,
              "partial_failure": 5, "profile_busy": 6}

# 只在单篇处理内部使用的错误码：它进的是状态库的 mark 与事件流，不会成为进程退出码
# （fetch 就地记成 empty 并继续跑）。列在这里是为了让「每个错误码都有归属」这条测试说得真话。
INTERNAL_ONLY_CODES = {"empty_content"}

# 这两条命令描述工具本身，因此在还没有任何配置时也必须能跑
CONFIGLESS_COMMANDS = frozenset({"init", "spec"})

ENVELOPE = {
    "stdout": "单个 JSON 信封；--jsonl 时是每行一个事件，末行 result 里才是同一个信封",
    "stderr": "给人看的进度（list/fetch 的丢弃原因也在这里）",
    "shape": {"ok": "bool", "data": "object|null", "error": "null | {code: str, message: str}"},
    "note": "非零退出也常带 data：fetch 中断前已存下的篇数与路径在 data.saved_paths 里，先读它再决定重跑",
}

CONFIG = {
    "search_order": ["--config", "HIBOR_CONFIG", "./config.yaml", "~/.hibor/config.yaml"],
    "resolution": "配置文件里的相对路径都以该文件所在目录为基准",
    "env": {"HIBOR_CONFIG": "配置路径", "HIBOR_PROFILE_DIR": "覆盖 profile_dir",
            "WEKNORA_BASE_URL": "覆盖 weknora.base_url", "WEKNORA_API_KEY": "覆盖 weknora.api_key"},
    "first_run": "装好后先 `hibor init`（写 ~/.hibor/config.yaml），再 `hibor login`（人工登录一次）",
}

# 每条命令：用途、参数、返回、以及 agent 需要知道的坑。flag 名与 --help 严格一致。
COMMANDS = [
    {
        "command": "hibor init",
        "purpose": "写出配置模板；系统级安装后的第一步，不需要已有配置",
        "args": [
            {"flag": "--path", "default": "~/.hibor/config.yaml", "help": "写到哪儿"},
            {"flag": "--profile-dir", "default": "<配置目录>/chrome-profile",
             "help": "Chrome 配置目录；想复用已有登录就填别处的 profile"},
            {"flag": "--force", "kind": "bool", "help": "覆盖已存在的配置"},
        ],
        "returns": {"config": "写出的路径", "profile_dir": "配置里记的 profile", "next": "建议的后续命令"},
        "exit_codes": [0, 1, 2],
    },
    {
        "command": "hibor spec",
        "purpose": "输出本契约（命令、参数、退出码、信封），不必读长文档",
        "args": [{"flag": "--config", "help": "只为解析出 config_path 一并返回，不改变其它行为"}],
        "returns": {"commands": "COMMANDS 表", "exit_codes": "码表", "envelope": "信封结构",
                    "config": "配置搜索顺序与环境变量", "config_path": "当前会用到哪个配置（没有则 null，并附 config_error）",
                    "version": "CLI 版本"},
        "exit_codes": [0, 1],
    },
    {
        "command": "hibor stock list",
        "purpose": "列出个股会处理的报告（不下载），标注 already_saved；相关性四道闸都已应用",
        "args": [
            {"flag": "name", "kind": "positional", "help": "个股简称或代码，如 紫金 / 601899"},
            {"flag": "--scope", "choices": ["title", "abstract", "fulltext"], "default": "title",
             "help": "关键词允许命中的位置；abstract 即慧搜网页上的「摘要」"},
            {"flag": "--keep-noise", "kind": "bool", "help": "关掉噪音闸（第四道），只在排查漏抓时用"},
            {"flag": "--days", "type": "int", "default": 7, "help": "最近 N 天"},
            {"flag": "--from", "metavar": "YYYY-MM-DD", "help": "起始日期，优先于 --days"},
            {"flag": "--to", "metavar": "YYYY-MM-DD", "help": "结束日期，配合 --from"},
            {"flag": "--max", "type": "int", "default": 100, "help": "最多处理篇数"},
            {"flag": "--jsonl", "kind": "bool", "help": "stdout 改输出事件流"},
            {"flag": "--config", "help": "配置路径"},
        ],
        "returns": {"folder": "分组目录名，如 个股_紫金", "count": "条数", "new": "其中尚未保存的条数",
                    "items": "[{id,url,title,published,org,column,authors,rating,pages,subject,already_saved,relevance}]"},
        "notes": ["被丢弃的条目不在 items 里，原因以 `~~ 丢弃 <标题>: <原因>` 走 stderr（--jsonl 时是 filtered 事件）",
                  "list 不写文件也不占 fetch 的额度，适合先探再抓"],
        "exit_codes": [0, 1, 2, 3, 4, 6],
    },
    {
        "command": "hibor stock fetch",
        "purpose": "抓取个股报告并存成 Markdown（output/<分组>/<文件名>）",
        "args": "same as stock list",
        "returns": {"folder": "分组目录名", "saved": "新存篇数", "skipped": "已存在跳过",
                    "empty": "无文字正文（图片型报告）", "failed": "本次失败", "filtered": "判为无关",
                    "saved_paths": "新存文件的绝对路径列表"},
        "notes": ["去重在 SQLite（state/reports.db，主键 报告ID+分组），done/empty/filtered 不再花详情页请求，failed 会重试",
                  "被相关性闸丢弃的条目不占 --max 名额"],
        "exit_codes": [0, 1, 2, 3, 4, 5, 6],
    },
    {
        "command": "hibor industry list",
        "purpose": "列出行业大类/细分行业会处理的报告（走行业列表页，不下载）",
        "args": [
            {"flag": "name", "kind": "positional", "help": "一级行业名，取值见 `hibor industries`"},
            {"flag": "--sub", "help": "细分行业"},
            {"flag": "--keyword", "help": "站点标题关键字过滤"},
            {"flag": "--days", "type": "int", "default": 7},
            {"flag": "--from", "metavar": "YYYY-MM-DD"},
            {"flag": "--to", "metavar": "YYYY-MM-DD"},
            {"flag": "--max", "type": "int", "default": 100},
            {"flag": "--jsonl", "kind": "bool"},
            {"flag": "--config", "help": "配置路径"},
        ],
        "returns": {"folder": "分组目录名，如 行业_有色金属", "count": "条数", "new": "尚未保存的条数", "items": "同 stock list"},
        "notes": ["行业页没有服务端日期过滤，按分享时间倒序翻到超出范围为止",
                  "行业任务没有 --scope：它不走慧搜，相关性四道闸也不干预"],
        "exit_codes": [0, 1, 2, 3, 4, 6],
    },
    {
        "command": "hibor industry fetch",
        "purpose": "抓行业报告并存 Markdown",
        "args": "same as industry list",
        "returns": "same as stock fetch",
        "exit_codes": [0, 1, 2, 3, 4, 5, 6],
    },
    {
        "command": "hibor status",
        "purpose": "查已抓取状态（不联网、不开浏览器）",
        "args": [
            {"flag": "--folder", "help": "只看某个分组，如 个股_紫金"},
            {"flag": "--failed", "kind": "bool", "help": "附带最近失败明细"},
            {"flag": "--limit", "type": "int", "default": 20},
            {"flag": "--config", "help": "配置路径"},
        ],
        "returns": {"folders": "[{folder,done,empty,filtered,failed}]", "failed": "失败明细（--failed 时）",
                    "config_path": "用的哪个配置"},
        "exit_codes": [0, 1, 2],
    },
    {
        "command": "hibor push",
        "purpose": "把 output 下的分组上传到 WeKnora 知识库（不联网到慧博，不开浏览器）",
        "args": [
            {"flag": "--kb", "required": True, "metavar": "NAME_OR_ID", "help": "知识库名称或 ID"},
            {"flag": "--stock", "kind": "list", "metavar": "NAME", "help": "推送这些个股分组（个股_<NAME>）"},
            {"flag": "--industry", "kind": "list", "metavar": "NAME", "help": "推送这些行业分组（行业_<NAME>）"},
            {"flag": "--create", "kind": "bool", "help": "库不存在时按名称新建"},
            {"flag": "--description", "help": "配合 --create 的新库描述"},
            {"flag": "--dry-run", "kind": "bool", "help": "只列会上传哪些篇"},
            {"flag": "--timeout", "type": "float", "default": 600.0, "help": "等解析完成的秒数上限"},
            {"flag": "--jsonl", "kind": "bool"},
            {"flag": "--config", "help": "配置路径"},
        ],
        "returns": {"kb": "{id,name}", "dry_run": "bool", "uploaded": "篇数", "completed": "解析完成篇数",
                    "already_in_kb": "重复跳过篇数", "failed": "[{folder,...}]，非空时退出码 5", "folders": "逐组明细"},
        "notes": ["按**文件名**与库里条目比对：改了文件名会被当新文件重传",
                  "不带 --stock/--industry 时遍历 output 下所有分组；这是写共享库的操作，先 --dry-run 并征询用户"],
        "exit_codes": [0, 1, 2, 3, 4, 5],
    },
    {
        "command": "hibor doctor",
        "purpose": "体检：Profile 占用、登录态、是否被限流（会开真实浏览器）",
        "args": [{"flag": "--config", "help": "配置路径"}],
        "returns": {"profile_dir": "Chrome 目录", "profile_busy": "bool", "logged_in": "bool|null",
                    "blocked": "bool|null", "config_path": "用的哪个配置"},
        "notes": ["logged_in=false（退出码 3）不代表抓不到：列表页与正文摘录对未登录会话是开放的，"
                  "只有额度/全文类内容受限"],
        "exit_codes": [0, 1, 2, 3, 4, 6],
    },
    {
        "command": "hibor industries",
        "purpose": "列出站点合法的行业大类与细分行业（industry --sub 的取值来源）",
        "args": [{"flag": "--config", "help": "配置路径"}],
        "returns": {"industries": "[{name, sub_industries:[...]}]"},
        "exit_codes": [0, 1, 2, 3, 4, 6],
    },
    {
        "command": "hibor login",
        "purpose": "打开 Chrome 让人工登录一次，会话留在 profile 目录",
        "args": [{"flag": "--config", "help": "配置路径"}],
        "returns": {"profile": "profile 目录", "saved": True},
        "notes": ["唯一需要人出面的命令：agent 不要自己跑，让用户跑，或请用户确认后再跑"],
        "exit_codes": [0, 1, 2, 6],
    },
]

RELEVANCE_GATES = [
    {"gate": "标题闸", "when": "列表期", "rule": "--scope title 时标题必须连着出现该名称，否则丢弃（慧搜是分词匹配）"},
    {"gate": "公司/行业二分", "when": "列表期", "rule": "subject 形如 601899(紫金矿业) 判 company 并恒留；(锡行业) 或空判 industry"},
    {"gate": "噪音闸", "when": "列表期", "rule": "晨会/早间资讯/行业数据/高频数据/日报周报这类例行壳子一律丢；"
                                               "定期研报、定期策略与「…点评/简评/快评」只在标题未点名本股时丢。--keep-noise 可关"},
    {"gate": "正文闸", "when": "详情期", "rule": "industry 类的正文摘录必须提到该名称，否则丢弃（精度换召回）"},
]

# agent 反复踩的坑，写成硬约束而不是散文
CONVENTIONS = [
    "stdout 永远只有一个 JSON 信封（--jsonl 是事件流），进度与丢弃原因走 stderr，不要用管道截断输出",
    "Windows 控制台是 GBK：解释器直跑时先设 PYTHONIOENCODING=utf-8；`hibor` 命令自己会把 stdout/stderr 改成 UTF-8",
    "PowerShell 5.1 用 GBK 解码子进程输出，中文会连尾引号一起吃掉，ConvertFrom-Json 因此报「无效 JSON」："
    "解析前先 `[Console]::OutputEncoding=[Text.Encoding]::UTF8`（cmd/Git Bash 里不需要，字节本来就是 UTF-8）",
    "一次只跑一个抓取进程：Chrome profile 同时只能被一个进程持有，第二个直接退出码 6",
    "退出码 3/4/6 之后不要写循环重试 —— 3 要人工 login，4 是被风控，换时间再跑；6 要先找出占用 profile 的进程",
    "不要调低配置里的 delay，也不要删 safedog-flow-item cookie 或把 cookie 导出给别的客户端",
    "抓的是详情页 .abstruct-info 的文字摘录，不是整份 PDF：回答用户时不要说成「全文已入库」",
    "参数不确定时跑 `hibor <命令> --help` 或 `hibor spec`，不要猜",
]

SPEC = {
    "name": "hibor",
    "install": "uv tool install --from git+https://github.com/yingpcao/hibor_cli_v1.git hibor-cli"
               "（在仓库里开发就换成目录路径，或用技能包自带的 scripts/setup.ps1 / setup.sh）",
    "envelope": ENVELOPE,
    "config": CONFIG,
    "exit_codes": {
        "0": "成功",
        "1": "未预期的内部错误，看 stderr 的 traceback",
        "2": "用法/配置错误（含库名不存在、缺 --config 目标）",
        "3": "登录失效，需要人工 `hibor login`",
        "4": "被限流/页面异常/连续失败，停止重试",
        "5": "跑完了但有报告抓取或解析未成功，明细在 data（或 status --failed）",
        "6": "Chrome profile 被占用，先解决占用",
    },
    "commands": COMMANDS,
    "relevance_gates": RELEVANCE_GATES,
    "conventions": CONVENTIONS,
}
