# Codex 用量统计

一个本地离线的 **Codex Desktop** 用量统计桌面应用。应用使用 Tauri 2 + Rust 构建，直接读取本机 `~/.codex/sessions` 日志，不依赖本地 HTTP 服务，不上传任何数据。

## 功能

- 中文桌面界面
- 范围筛选：全部 / 30 天 / 7 天
- 主指标：有效 token = 非缓存输入 + 输出
- 展示原始总 token、缓存输入、非缓存输入、输出和推理输出
- 每日有效 token 趋势图
- 最近 53 周有效 token 热力图
- 刷新按钮重新读取 sessions 目录
- 系统托盘支持显示窗口、退出、查看今日/7 天/30 天有效 token
- 关闭窗口时隐藏到托盘

## 启动

开发运行：

```bat
run.bat
```

或直接运行：

```bat
npm install
npm run tauri
```

## 构建

本机工具链路径：

- Rust：`D:\Apps\Rust`
- Visual Studio Build Tools：`D:\Apps\Microsoft Visual Studio\2022\BuildTools`
- Tauri CLI：项目本地 `node_modules`

构建 Windows 安装包：

```bat
build-tauri.bat
```

构建产物：

```text
src-tauri\target\release\codex-usage-stats.exe
src-tauri\target\release\bundle\nsis\Codex 用量统计_0.2.0_x64-setup.exe
```

## 数据来源

Codex Desktop 的会话日志位于：

```text
~/.codex/sessions/YYYY/MM/DD/rollout-<start_ts>-<uuid>.jsonl
```

应用读取每个 session 最后一条非空的：

```text
event_msg.token_count.info.total_token_usage
```

## Token 口径

| 指标 | 定义 |
|---|---|
| 有效 token | `(input_tokens - cached_input_tokens) + output_tokens` |
| 原始总 token | Codex 日志里的 `total_tokens`，包含缓存输入 |
| 非缓存输入 | `input_tokens - cached_input_tokens` |
| 缓存输入 | `cached_input_tokens` |
| 输出 token | `output_tokens` |
| 推理输出 | `reasoning_output_tokens`，属于输出 token 的细分，不重复加算 |

## 项目结构

```text
src-tauri/
  src/main.rs        # Tauri/Rust 后端，读取 sessions 并聚合统计
tauri-ui/
  index.html         # 桌面界面
  app.js             # 图表和交互
```

## 隐私

本工具只读取本机 session 文件，不写入、不上传、不发送日志内容。`.gitignore` 排除了真实 sessions 和 `*.jsonl`，避免误提交真实日志。

## License

MIT
