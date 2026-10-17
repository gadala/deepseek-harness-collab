# DeepSeek Harness Collab

**让 Codex 做项目总负责人，让真实 DeepSeek Harness CLI 会话组成项目团队。**

A Codex skill for supervising real, headless DeepSeek Harness sessions as departments,
with native child agents as members and independent acceptance of every delivery.

> 社区协作 Skill，非 OpenAI 或 DeepSeek 官方项目；不包含 Harness 程序、模型权重、API 密钥、认证数据或专有运行时补丁。

## 团队结构

```text
Codex：总负责人、依赖/写权分配、独立验收
├── Harness 主会话：实现部门
│   ├── 原生 child：模块 A
│   └── 原生 child：模块 B
└── Harness 主会话：测试/文档部门
    └── 原生 child：限定工作包
```

部门是实际 headless CLI 主会话，不是必须打开的桌面窗口；成员是 Harness 原生子 agent，不是 Codex 子 agent。部门退出后不能当作常驻服务。

## 能做什么

- 按依赖拆分工作包；无冲突写集的部门可并发调度。
- 支持向真实子 agent 分派窄任务、增量返修、短汇报和证据索引。
- 本地脚本登记写权、检测资源冲突、核对证据 hash 和交接状态。
- Codex 独立检查 diff、范围、负例、契约、消费者接线和集成回归。
- 每 3 次有效部门任务做 `continue / compact / renew` 判断，而非强制重建。
- 缩短汇报和重复上下文，不删质量门：`delivered != passed`。

**这不是一键自主运行的团队平台。** 脚本不会启动、关闭或恢复 agent，也不是文件权限沙箱。并发、取消、续接和成员能力须按实际安装核验。

## 环境要求

1. 可加载本地 Skills 的 Codex 环境。
2. 已由用户合法安装并完成正常认证的 DeepSeek Harness，具有可用的 headless CLI/profile。
3. Python **3.10+** 用于辅助脚本与本地测试；运行脚本仅依赖标准库。
4. 项目任务的明确授权、工作目录、读写集与验收标准。

历史子 agent 能力摘要来自 Harness `0.1.5-rc.2`，不构成对所有版本的兼容承诺。发现缺插件或认证失败时应报告阻塞，不自动安装、不改变认证或提升权限。

## 安装

### Windows / PowerShell

将下方仓库地址占位符替换成实际发布地址。目标目录若已存在，先确认和保留本地修改，不要直接覆盖。

```powershell
$skillsRoot = if ($env:CODEX_HOME) {
    Join-Path $env:CODEX_HOME 'skills'
} else {
    Join-Path $HOME '.codex/skills'
}
New-Item -ItemType Directory -Force -Path $skillsRoot | Out-Null
git clone https://github.com/gadala/deepseek-harness-collab.git (Join-Path $skillsRoot 'deepseek-harness-collab')
```

### macOS / Linux

```sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/gadala/deepseek-harness-collab.git "${CODEX_HOME:-$HOME/.codex}/skills/deepseek-harness-collab"
```

如界面未刷新，重新打开或创建 Codex 会话。路径发现与 Windows 发行包说明不等于跨平台 Harness 已验证支持；辅助脚本的测试与真实模型能力验证应分开看待。

## 使用

在 Codex 中明确调用：

```text
使用 $deepseek-harness-collab 管理这个项目。
先核对当前项目纪律、CLI/profile、cwd、基线和写权。
将实现和测试拆成无写集冲突的工作包，由真实 Harness 执行；
未经独立验收不得标完成，不允许部署或推送代码。
```

任务卡至少包含：目标/非目标、实际 cwd、精确读写集、禁止路径、基线/接口 hash、依赖、验收命令/负例、证据路径、超时/有限重试和报告要求。

请先读 [SKILL.md](SKILL.md)。按需再读 [团队模型](references/team-operating-model.md)、[并发调度](references/parallel-orchestration.md) 与 [执行协议](references/execution-protocol.md)，不必每次全文加载。

## 默认时段和预算：需要按项目确认

该版本保留原始默认策略：北京时间周一至周五 `[09:00,12:00)`、`[14:00,18:00)` 避峰；周末（即使调休）和官方完整放假区间允许。`budgetPolicy=unlimited` 是不人为封顶，不是费用免费或无限并发。

**用户当前指令和项目最新生效纪律优先。** 默认时间门脚本固定实现避峰规则；项目允许全天候运行时应先适配策略和对应脚本，不能让旧默认覆盖新授权，亦不能伪造 gate 结果。仓库只附带 2026 年日历；未知年份在需要日历判定的高峰窗保守阻塞。

时间门只是只读派发前检查，不是请求代理或强制终止器；模型内部、重试、成员请求与跨窗运行仍需另外控制。`--at` 只用于测试/重放，不能在真实派发中伪造时钟。

```powershell
python -B -X utf8 scripts/work_time_gate.py
python -B -X utf8 scripts/execution_protocol.py --help
```

## 本地验证

从本仓库根目录运行，无需模型调用、Harness、API 密钥或联网：

```sh
python -B -m unittest discover -s scripts -p "test_*.py" -v
```

CI 配置在 Windows/Linux、Python 3.10/3.12 上运行同一命令；提交了配置不代表远端 CI 已通过。测试验证本地 gate 和协议行为，不证明真实模型、多部门负载或子 agent 当前可用。

## 发布内容与安全

- 公开副本仅含 Skill 指令、辅助源码、测试、日历和脱敏能力摘要。
- 不分发个人机器路径、真实会话 ID、原始 transcript、认证数据和业务项目文件。
- 本机专属执行通道修复不包含在内，不应复制到别人的环境。
- 发现双 writer、越权写或停止状态未知时先冻结受影响写权。
- 不默认允许 commit/push/部署/生产回退；认证失败不切换桌面控制路线。
- 安全问题见 [SECURITY.md](SECURITY.md)。

## License

本仓库原创内容采用 [MIT License](LICENSE)。DeepSeek Harness、Codex 和第三方运行时由各自权利人与条款约束；本许可证不授予第三方软件、商标或服务权限。
