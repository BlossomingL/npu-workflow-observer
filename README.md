# NPU Workflow Observer v0.2

一个**本地优先（Local-first）**的 NPU 研发工作流观察器。

它的目标不是录屏，而是把你真实的研发过程：

```text
你给 Cursor / Codex 下任务
        ↓
Coding Agent 阅读 / 修改代码
        ↓
执行 Shell / Build / Test
        ↓
上板 / 精度 / Benchmark / Profile
        ↓
得到结果
        ↓
继续修改 / 形成结论
```

转换成结构化 Trace，后续用于：

```text
Workflow Mining
    ↓
Shadow Agent
    ↓
Workflow → Agent Compiler
    ↓
Test / Debug / Precision / Performance Agent
```

---

## v0.2 的重点：观察 Cursor / Codex

如果你的大部分研发工作已经通过 Cursor 或 Codex 完成，那么 Observer 的核心数据源就不应该只是键盘、终端和 VSCode 文件保存，而应该包括 **Coding Agent 自己的工作轨迹**。

v0.2 新增：

- Cursor Agent Hooks 观察；
- 一条命令安装 Cursor hooks；
- 记录用户 Prompt；
- 记录 Agent 最终回复；
- 记录 Agent 文件修改；
- 记录 Agent Shell / Tool 调用结果；
- 记录 Agent Task / Session 生命周期；
- Codex rollout JSONL 导入；
- Codex session 实时 watch；
- 自动发现新 Codex session，不需要每次重启 watcher；
- 自动把 Shell / Test / Profile 事件关联到最近的 Coding Agent trace；
- Workflow Miner 自动过滤 token usage、重复 transcript record 等低价值噪声；
- Python 3.10 / 3.12 GitHub Actions 单元测试。

### 一个重要的隐私设计

Observer **不会保存模型隐藏 reasoning / chain-of-thought 内容**。

对于 Cursor `afterAgentThought` 和 Codex reasoning record，只记录：

```text
agent.thought.completed
content_recorded = false
duration_ms = ...   # 如果数据源提供
```

我们真正需要学习的是可审计信息：

```text
Prompt
Tool Call
Patch
Build/Test/Profile
Result
Decision
Final Response
```

而不是模型内部思维链。

---

# 1. 安装

```bash
git clone https://github.com/BlossomingL/npu-workflow-observer.git
cd npu-workflow-observer

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

确认：

```bash
npu-observer --help
```

主要命令：

```text
daemon
exec
git-snapshot
decision
event
agent-hook
cursor-install
import-codex
watch-codex
link-agent
sessionize
mine
```

默认数据库：

```text
~/.npu-observer/observer.db
```

可以修改：

```bash
export NPU_OBSERVER_HOME=/path/to/private/storage
```

---

# 2. Cursor：推荐使用官方 Hooks 接入

Cursor 当前支持 Agent Hooks，例如：

```text
sessionStart
sessionEnd
beforeSubmitPrompt
afterShellExecution
afterFileEdit
postToolUseFailure
afterAgentResponse
afterAgentThought
stop
```

Observer 使用这些 Hook 获取 Agent 的结构化行为，不需要录屏。

## 用户级安装

```bash
npu-observer cursor-install --scope user
```

会安全地合并到：

```text
~/.cursor/hooks.json
```

不会覆盖已有 hooks，并且重复执行是幂等的。

## 仅当前项目安装

在目标代码仓中执行：

```bash
npu-observer cursor-install --scope project
```

生成 / 合并：

```text
<project>/.cursor/hooks.json
```

也可以指定路径：

```bash
npu-observer cursor-install --path /custom/path/hooks.json
```

### Cursor 会记录什么

典型事件：

```text
agent.task.started
agent.prompt.submitted
agent.tool.completed
agent.patch.applied
agent.tool.failed
agent.response.completed
agent.thought.completed   # 不保存 thought 文本
agent.task.completed
agent.session.completed
```

Cursor 如果提供 `CURSOR_TRANSCRIPT_PATH`，Observer 会基于该路径生成稳定 session id，将同一次对话里的事件关联起来。

---

# 3. Codex：直接观察本地 rollout JSONL

Codex CLI / App 会把会话记录保存在类似：

```text
$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl
```

默认 `CODEX_HOME` 通常是：

```text
~/.codex
```

## 导入最近的 Codex 会话

```bash
npu-observer import-codex --latest 20
```

或者指定某个 rollout：

```bash
npu-observer import-codex \
  --path ~/.codex/sessions/2026/09/17/rollout-xxx.jsonl
```

重复导入不会重复写入相同 record，因为 Codex event id 是确定性生成的，SQLite 使用唯一 `event_id` 去重。

## 实时观察 Codex

```bash
npu-observer watch-codex
```

它会持续扫描：

```text
~/.codex/sessions
```

并自动发现新创建的 rollout session。

如果只想观察一个 session：

```bash
npu-observer watch-codex --path /path/to/rollout.jsonl
```

解析的核心语义包括：

```text
session_meta        → agent.session.started
user_message        → agent.prompt.submitted
task_started        → agent.task.started
function_call       → agent.tool.started
function_call_output→ agent.tool.completed
assistant message   → agent.response.record
task_complete       → agent.task.completed
reasoning           → metadata only，不保存正文
```

解析器支持当前 Codex `session_meta.payload.meta` 嵌套结构，并会从 session metadata 中继承 cwd，使后续 tool / message record 能正确归属到代码仓。

---

# 4. Shell / NPU Test 事件

原有能力仍然保留。

## 显式观察 Shell 命令

```bash
npu-observer exec -- cmake --build build -j32
npu-observer exec -- ./run_test.sh --shape 2,32,4096,128
npu-observer exec -- nsys profile ./benchmark
```

记录：

```text
command
cwd
exit_code
duration
git branch / commit
command role
```

## NPU 领域事件

例如：

```bash
npu-observer event npu.test.completed --source adapter \
  --attributes '{
    "operator":"flash_attention_score_grad",
    "shape":{"B":2,"N":32,"S":4096,"D":128},
    "dtype":"bf16",
    "layout":"TND",
    "pass":true
  }'
```

精度：

```bash
npu-observer event npu.accuracy.completed --source adapter \
  --attributes '{
    "cosine":0.99998,
    "max_abs":0.0021,
    "pass":true
  }'
```

性能：

```bash
npu-observer event npu.benchmark.completed --source adapter \
  --attributes '{
    "latency_us":182.4,
    "mfu":0.831
  }'
```

---

# 5. 把 Agent 和真实测试结果串到一起

这是 v0.2 很关键的一步。

假设 Codex 做了：

```text
Prompt
 → 修改 tiling
 → build
 → run test
 → profile
 → 再改代码
```

Coding Agent 的事件天然带 `trace_id`，但是你的外部测试脚本可能没有。

执行：

```bash
npu-observer link-agent --window 30
```

Observer 会保守地按照：

```text
same repository
+
最近 Coding Agent trace
+
30 分钟时间窗口
```

将没有 trace 的 Shell / NPU Test / Profile 事件关联到 Coding Agent trace。

然后：

```bash
npu-observer sessionize
```

如果某个 trace 已确认属于 Cursor / Codex，那么同 trace 的：

```text
Prompt
Patch
Shell
Accuracy
Benchmark
Profile
```

会被放进同一个 Session，而不是再次被拆开。

---

# 6. 从真实 Agent Session 归纳 Workflow

```bash
npu-observer mine \
  --min-support 0.5 \
  --name fa_grad_agent_workflow \
  -o workflow.generated.yaml
```

Workflow Miner 默认忽略：

```text
agent.thought.completed
agent.usage.updated
agent.session.record
重复 transcript message record
```

重点保留：

```text
agent.prompt.submitted
agent.patch.applied
agent.tool.*
build
test
npu.accuracy.*
npu.benchmark.*
profile
decision.created
agent.task.completed
```

例如未来可能得到：

```yaml
name: "fa_grad_agent_workflow"
version: 1
steps:
  - agent_prompt_submitted:
      observed: true
  - agent_patch_applied:
      observed: true
  - build:
      observed: true
  - npu_accuracy_completed:
      observed: true
  - npu_benchmark_completed:
      observed: true
```

当前仍然故意保留：

```yaml
tool: TODO
```

因为：

```text
Workflow Discovery
        ≠
立即允许 Agent 自动执行
```

推荐过程：

```text
Observe
  ↓
Mine
  ↓
人工 Review
  ↓
Shadow Agent
  ↓
Approval Mode
  ↓
Autonomous Agent
```

---

# 7. 专家决策仍然非常重要

Agent 操作轨迹能告诉我们：

```text
发生了什么
```

但并不总能可靠告诉我们：

```text
为什么保留这个优化方案
```

因此仍然支持：

```bash
npu-observer decision \
  -m "tile_n 128 -> 256" \
  --reason "MTE bound，Cube 利用率低" \
  --evidence "profile=run_001"
```

未来也可以由上层 Agent 自动输出结构化：

```json
{
  "hypothesis": "MTE bound",
  "evidence": ["Cube util 57%", "MTE util 92%"],
  "action": "increase tile_n",
  "result": "latency -8.2%"
}
```

---

# 8. 数据模型

所有数据最后统一成 Event：

```json
{
  "event_id": "...",
  "timestamp": "...",
  "name": "agent.patch.applied",
  "source": "agent:cursor",
  "trace_id": "...",
  "session_id": "...",
  "cwd": "/repo/ops-transformer",
  "attributes": {
    "agent": {
      "provider": "cursor"
    },
    "git": {
      "branch": "perf_d128",
      "commit": "..."
    }
  }
}
```

有持续时间的操作未来会逐步向 OpenTelemetry Span 靠拢；瞬时状态变化保持 Event。

---

# 9. 安全与隐私

默认原则：

- 本地 SQLite 存储；
- daemon 只监听 `127.0.0.1`；
- token / password / API key 做基础脱敏；
- 不记录原始键盘输入；
- 不记录剪贴板；
- 不默认截图；
- 不保存模型隐藏 reasoning / thought 正文；
- Git diff 有长度上限；
- Agent / Tool 文本有长度上限；
- Workflow 在 Review 前不自动执行源码修改、部署或上板操作。

公司环境建议继续加入：

```text
repo/path allowlist
source_capture = none | metadata | git_diff
Artifact Store
加密磁盘
日志保留周期
敏感路径 denylist
```

---

# 10. 推荐日常使用方式

## Cursor 用户

安装一次：

```bash
npu-observer cursor-install --scope user
```

之后正常用 Cursor 工作即可。

## Codex 用户

开一个终端：

```bash
npu-observer watch-codex
```

然后正常用 Codex。

## 一段时间后归纳

```bash
npu-observer link-agent --window 30
npu-observer sessionize --gap 45
npu-observer mine --name fa_grad_workflow
```

---

# 11. 当前架构

```text
              Human
                │
        ┌───────┴────────┐
        ▼                ▼
     Cursor             Codex
   Official Hooks    rollout JSONL
        │                │
        └───────┬────────┘
                ▼
        Coding Agent Adapter
                │
      ┌─────────┼──────────┐
      ▼         ▼          ▼
    Git       Shell      NPU Adapter
      │         │          │
      └─────────┼──────────┘
                ▼
          Unified Event DB
                │
          Trace Linker
                │
          Sessionizer
                │
          Workflow Miner
                │
                ▼
        workflow.generated.yaml
```

---

# 12. 测试

本地：

```bash
python -m unittest discover -s tests -v
```

GitHub Actions 当前覆盖：

```text
Python 3.10
Python 3.12
```

核心测试包括：

- command classification；
- SQLite Event Store；
- Sessionize / Workflow Mining；
- Cursor Hook 返回协议；
- Cursor hooks 幂等安装；
- Cursor thought 内容不落盘；
- Codex nested session metadata；
- Codex UUID / cwd 关联；
- Coding Agent trace linking。

---

# 下一阶段

## v0.3：NPU Native Adapter

重点接入真实 NPU 研发环境：

```text
Build Adapter
Board / Device Adapter
Accuracy Adapter
Benchmark Adapter
Profiler Adapter
Shape Parser
```

最终让你日常只需要正常对 Cursor / Codex 说：

```text
帮我优化这个 FA Grad shape 的性能
```

Observer 就能自动积累：

```text
Prompt
→ Agent 修改
→ Build
→ Shape
→ 上板
→ Accuracy
→ Latency / MFU
→ Profile
→ 下一轮修改
→ 最终结论
```

这才是后续自动生成 NPU Test / Debug / Performance Agent 的训练数据基础。
