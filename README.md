# Codex 用量统计

一个本地离线的 **Codex Desktop** 用量面板。它读取本机
`~/.codex/sessions` 日志，展示有效 token、原始总 token、缓存输入、
输出 token、会话数、活跃天数、常用模型、每日趋势和热力图。

不需要登录，不写数据库，不上传数据。现在推荐使用 Tauri 桌面版；
旧的 Python 本地网页版本仍保留，方便调试和对照。

<!-- Add a screenshot: docs/screenshot.png -->

## 功能

- 范围筛选：全部 / 30 天 / 7 天
- 主指标：有效 token = 非缓存输入 + 输出
- 保留原始总 token、缓存输入、非缓存输入、输出和推理输出
- 每日有效 token 趋势图
- 最近 53 周有效 token 热力图
- 刷新按钮会重新读取 sessions 目录
- 桌面版直接读取本机 sessions，不依赖本地 HTTP 服务
- Python 版本支持 `CODEX_HOME` 环境变量或 `--path` 指定路径

## 启动桌面版

已安装的本机工具链：

- Rust：`D:\Apps\Rust`
- Visual Studio Build Tools：`D:\Apps\Microsoft Visual Studio\2022\BuildTools`
- Tauri CLI：项目本地 `node_modules`

开发运行：

```bat
run-tauri.bat
```

构建安装包：

```bat
build-tauri.bat
```

已验证可生成：

```text
src-tauri\target\release\codex-usage-stats.exe
src-tauri\target\release\bundle\nsis\Codex 用量统计_0.2.0_x64-setup.exe
```

## 启动旧版网页

```sh
python -m codex_stats
```

Windows 下也可以双击 `run.bat`。可传入参数，例如：
`run.bat --port 8080 --no-browser`。

### Options

```
--path PATH     Codex home directory (default: $CODEX_HOME or ~/.codex)
--host HOST     Bind host (default: 127.0.0.1)
--port PORT     Bind port (default: 0 → pick a free port)
--no-browser    Don't auto-open a browser tab
```

## 构建旧版 Python `.exe`

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# → dist\codex-stats.exe
```

The exe is standalone — double-click it, a browser tab opens.

## 数据来源

Codex Desktop writes one JSONL file per session at:

```
~/.codex/sessions/YYYY/MM/DD/rollout-<start_ts>-<uuid>.jsonl
```

Each line is `{timestamp, type, payload}`. The parser only looks at four
`type`s: `session_meta`, `turn_context`, `event_msg`, `response_item`.

每行是 `{timestamp, type, payload}`。解析器主要读取：

- `session_meta`：会话元信息
- `turn_context`：模型、时区等
- `event_msg/token_count`：Codex 写入的 token 用量

## Token 口径

解析器取每个 session 最后一条非空的：

```text
event_msg.token_count.info.total_token_usage
```

这是 Codex 写入的会话累计值。面板不会累加 `last_token_usage`，因为真实日志里
`last_token_usage` 简单相加会经常高于最终累计值。

| Metric | Definition |
|---|---|
| **有效 token** | `(input_tokens - cached_input_tokens) + output_tokens`。这是面板主指标，用来近似表示真正主要消耗。 |
| **原始总 token** | `total_tokens`，Codex 日志里的会话累计总量，包含缓存输入。 |
| **非缓存输入** | `input_tokens - cached_input_tokens`。 |
| **缓存输入** | `cached_input_tokens`。缓存输入不计入有效 token，但严格 credits/API 计费时通常不是完全免费，而是折扣计价。 |
| **输出 token** | `output_tokens`。`reasoning_output_tokens` 是输出里的细分，不重复加到有效 token。 |
| **会话数** | 范围内 rollout 文件数量。 |
| **活跃天数** | `session_meta.timestamp` 对应的本地日期去重数量。 |
| **常用模型** | `turn_context.payload.model` 出现次数最多的模型。 |

## 开发

```sh
python tests/test_parser.py
python -m codex_stats --path tests/fixtures
npm install
run-tauri.bat
```

项目结构：

```
codex_stats/
  __main__.py   # CLI entry
  server.py     # stdlib HTTP server + JSON API
  parser.py     # JSONL → SessionSummary
  stats.py      # SessionSummary list → dashboard dict
  paths.py      # resolve CODEX_HOME / ~/.codex
web/
  index.html
  app.js        # dashboard renderer (vanilla JS + SVG)
tests/
  test_parser.py
  fixtures/sessions/...   # anonymized minimal sessions
src-tauri/
  src/main.rs             # Tauri/Rust desktop backend
tauri-ui/
  index.html
  app.js                  # Tauri desktop dashboard renderer
```

## 隐私

本工具只读取本机 session 文件，不写入、不上传、不发送日志内容。
`.gitignore` 排除了真实 sessions 和 `*.jsonl`，避免误提交真实日志。

## License

MIT
