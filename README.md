# NPU Workflow Observer MVP

一个**本地优先（Local-first）**的 NPU 研发工作流观察器，用于把日常 NPU 算子开发过程转成结构化 Trace，后续可进一步编译成可复用的 Workflow / Agent。

这个项目的目标不是录屏，而是把“改代码 → 编译 → 上板 → 测试 → 精度分析 → 性能分析 → 决策 → 再优化”这类研发过程记录成可分析、可归纳、可复用的数据。

## 当前 MVP 能记录什么

- Shell 命令、退出码、执行耗时、工作目录，以及命令角色（`build/test/benchmark/profile/remote`）。
- Git 仓库、分支、commit、dirty 状态，以及可选的 diff。
- VSCode 文件保存事件 + Git diff。
- 显式的 `decision.created` 专家决策事件，用来记录“为什么要这样改”。
- NPU 领域事件，例如 `npu.test.*`、`npu.accuracy.*`、`npu.benchmark.*`。
- 自动把零散事件聚合成一次研发 Session。
- 从多个 Session 中归纳 Workflow，并生成 `workflow.generated.yaml`。

Observer daemon 默认只监听 `127.0.0.1`，当前没有任何云端上传逻辑。

## 安装

```bash
cd npu-workflow-observer
python -m venv .venv
source .venv/bin/activate
pip install -e . --no-build-isolation
```

## 1. 启动 Observer

```bash
npu-observer daemon
```

默认数据库路径：

```text
~/.npu-observer/observer.db
```

也可以自定义存储目录：

```bash
export NPU_OBSERVER_HOME=/path/to/private/storage
npu-observer daemon
```

## 2. 记录命令

### 推荐第一步：显式 wrapper

先不要一上来全自动 Hook Shell，建议先通过 wrapper 验证行为是否符合预期：

```bash
npu-observer exec -- cmake --build build -j32
npu-observer exec -- ./run_test.sh --shape 2,32,4096,128
npu-observer exec -- nsys profile ./benchmark
```

Wrapper 会记录：

- 命令开始/结束时间
- return code
- 执行耗时
- cwd
- Git 上下文
- 命令类型

### 可选：自动 Bash Hook

```bash
source /path/to/npu-workflow-observer/scripts/bash_hook.sh
```

本地验证稳定后，可以把这一行加入：

```bash
~/.bashrc
```

这个 Hook 只记录命令级元数据，**不会记录原始键盘输入、剪贴板或屏幕截图**。

## 3. 记录 Git 状态

```bash
npu-observer git-snapshot
```

默认会保存当前 working tree diff。

如果只想记录 Git 元信息，不记录源码 diff：

```bash
npu-observer git-snapshot --no-diff
```

## 4. 记录专家决策

这一类信息非常重要，因为仅仅记录“用户做了什么”，并不能让 Agent 学会“为什么这么做”。

例如：

```bash
npu-observer decision \
  -m "tile_n 从 128 调整到 256" \
  --reason "MTE bound，Cube 利用率偏低" \
  --evidence "profile=run_20260917_01"
```

理想情况下，未来 Observer 可以把下面这些信息关联起来：

```text
Profile 结果
    ↓
识别瓶颈
    ↓
专家决策
    ↓
代码修改
    ↓
重新测试
    ↓
性能变化
```

这部分数据以后会成为 Performance Agent 最重要的经验来源之一。

## 5. 发送 NPU 领域事件

建议在已有测试、精度、benchmark、profiler 工具外面增加 Adapter，把原始执行结果转换成统一事件。

例如测试开始：

```bash
npu-observer event npu.test.started --source adapter \
  --attributes '{"operator":"flash_attention_score_grad","shape":{"B":2,"N":32,"S":4096,"D":128},"dtype":"bf16","layout":"TND"}'
```

精度测试完成：

```bash
npu-observer event npu.accuracy.completed --source adapter \
  --attributes '{"operator":"flash_attention_score_grad","cosine":0.99998,"max_abs":0.0021,"pass":true}'
```

性能测试完成：

```bash
npu-observer event npu.benchmark.completed --source adapter \
  --attributes '{"operator":"flash_attention_score_grad","latency_us":182.4,"mfu":0.831}'
```

可以参考：

```text
examples/test_flow.sh
```

## 6. 自动生成 Session

```bash
npu-observer sessionize --gap 45
```

当前 MVP 会优先按照：

```text
repository
+
branch
+
时间间隔
```

对事件做聚合。

当连续两个事件间隔超过 45 分钟时，会切分成新的 Session。

后续计划继续加入：

```text
operator
shape
task id
git diff
device
remote target
```

等信息，提高 Session 聚合准确度。

## 7. 从 Session 中归纳 Workflow

```bash
npu-observer mine \
  --min-support 0.5 \
  --name fa_grad_test \
  -o workflow.generated.yaml
```

示例输出：

```yaml
name: fa_grad_test
version: 1
generated_from_sessions: 8
steps:
  - source_file_saved:
      tool: TODO
      observed: true
  - build:
      tool: TODO
      observed: true
  - npu_test_completed:
      tool: TODO
      observed: true
  - npu_benchmark_completed:
      tool: TODO
      observed: true
```

第一版会故意保留：

```yaml
tool: TODO
```

原因是：

> Workflow 发现和 Agent 自动执行应该分阶段进行。

推荐演进路径：

```text
Observer Mode
    ↓
Workflow Discovery
    ↓
人工 Review
    ↓
Shadow Mode
    ↓
Approval Mode
    ↓
Autonomous Mode
```

在 Workflow 没有经过验证前，不应该直接允许 Agent 自动改代码、部署或上板执行。

## VSCode 扩展

当前 VSCode Extension 支持：

- 文件保存时记录 `source.file.saved`
- 自动附带 Git diff
- 在 Command Palette 中执行 `NPU Observer: Record Decision`

编译扩展：

```bash
cd vscode-extension
npm install
npm run compile
```

之后可以使用 VSCode Extension Development Host 调试。

如果需要打包为 VSIX，可以使用：

```text
@vscode/vsce
```

## Event 数据模型

每条事件大致长这样：

```json
{
  "event_id": "uuid",
  "timestamp": "2026-09-17T16:00:00+08:00",
  "name": "npu.benchmark.completed",
  "kind": "event",
  "source": "adapter",
  "cwd": "/repo/ops-transformer",
  "attributes": {
    "operator": "flash_attention_score_grad",
    "shape": {
      "B": 2,
      "N": 32,
      "S": 4096,
      "D": 128
    },
    "latency_us": 182.4,
    "mfu": 0.831,
    "git": {
      "branch": "perf_d128",
      "commit": "..."
    }
  }
}
```

推荐把它理解成一套面向 NPU 研发场景的轻量级 Trace/Event 数据模型。

后续可以逐步向 OpenTelemetry 风格演进：

```text
Build / Test / Profile
    → Span

Error / Decision / Commit
    → Event
```

## 隐私与安全默认策略

CLI 当前会对常见的 token、password、API key 等内容做基础脱敏。

实际在公司研发环境使用时，建议进一步加固：

- 数据库只存放在加密本地磁盘。
- 增加 repository / path allowlist。
- 大型日志、Profiler 数据不要直接塞进数据库，而是放入内容寻址 Artifact Store。
- 永远不要采集 `~/.ssh`、凭据文件、剪贴板或原始键盘输入。
- Source Capture 支持模式配置，例如 `metadata`、`git_diff`、`none`。
- Agent 在修改源码、部署和上板前必须经过权限审批。
- Shell 环境变量默认只允许白名单字段进入 Observer。

## 当前架构

```text
Shell / Git / VSCode / Test Adapter
              |
              v
       localhost JSONL
              |
              v
        observer daemon
              |
              v
           SQLite
              |
       +------+-------+
       |              |
  sessionizer    workflow miner
       |              |
       +-------> workflow.yaml
```

当前 MVP 使用 SQLite，主要原因是：

- Python 标准库自带
- 安装零依赖
- 方便快速落地
- 足够支撑早期 Trace 数据量

Storage 接口保持得比较小，后续数据量增大后可以切换到 DuckDB，用于更复杂的分析和 Workflow Mining。

## 推荐的使用方式

第一阶段不要追求“全自动 Agent”。

建议先让 Observer 安静记录真实研发流程：

```text
改代码
  ↓
编译
  ↓
部署
  ↓
测试
  ↓
精度分析
  ↓
性能分析
  ↓
Profiler
  ↓
专家决策
  ↓
再次修改
```

积累一定数量的 Session 后，再开始做 Workflow Mining。

目标不是机械复现用户点击了什么，而是最终学习：

```text
什么情况下
    ↓
应该执行什么步骤
    ↓
依据是什么
    ↓
如何判断成功/失败
    ↓
下一步应该做什么
```

## 下一阶段开发计划

### v0.2：Artifact Store

支持 stdout / stderr / profile / report 等大文件使用 SHA-256 URI 管理，例如：

```text
artifact://sha256/xxxxx
```

### v0.3：NPU 原生 Adapter

直接对接：

- Build
- Device / Board Runner
- Accuracy
- Benchmark
- Profiler

尽量减少手工执行 `npu-observer event ...`。

### v0.4：Shape 识别与上下文关联

自动识别：

```text
B / N / S / D
TND / BSH / SBH
causal
sparse
FP16 / BF16 / FP8
```

并关联后续 build / test / benchmark / profile。

### v0.5：Workflow Branch

支持自动归纳分支，例如：

```text
accuracy pass
    ↓
benchmark

accuracy fail
    ↓
precision debug
```

以及：

```text
performance regression
    ↓
profile
    ↓
bottleneck analysis
```

### v0.6：Shadow Agent

Agent 不直接执行，只预测下一步：

```text
Human 实际动作
vs
Agent 预测动作
```

统计：

- Step Accuracy
- Branch Accuracy
- Parameter Accuracy
- Final Result Accuracy

达到要求后，再逐步开放自动执行权限。

### v0.7：Workflow → Agent Compiler

把已经 Review 的：

```text
workflow.yaml
```

进一步编译成：

```text
skills/
├── SKILL.md
├── workflow.yaml
├── tools/
└── evals/
```

最终目标是逐渐形成：

```text
NPU Workflow Observer
        ↓
Workflow Miner
        ↓
Workflow Compiler
        ↓
Test Agent
Precision Debug Agent
Bug Debug Agent
Performance Agent
```

## 最终目标

NPU Workflow Observer 的最终定位不是监控软件，而是：

> **持续观察真实 NPU 算子研发过程，并把专家经验逐步编译成可复用 Agent 的基础设施。**

理想状态下，未来只需要输入：

```text
B=2
N=64
S=8192
D=128
layout=TND
causal=true
```

Agent 就能基于 Observer 学到的真实 Workflow 自动完成：

```text
构造用例
→ 编译
→ 部署
→ 上板
→ 精度验证
→ 性能测试
→ 性能回归判断
→ 必要时 Profile
→ 输出分析报告
```
