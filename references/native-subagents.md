# Harness 原生子 agent：真实用法与边界

仅在部门主会话需要成员时读取。本文件描述 Harness 内部工具，不是 Codex `multi_agent` API，也不是 `dsh subagent` CLI 子命令。

## 已核验能力（北京时间 2026-10-05）

证据：[../assets/native-subagent-probe-summary.json](../assets/native-subagent-probe-summary.json)。历史环境为 `dsh 0.1.5-rc.2`、`headless` profile；公开文件仅为脱敏历史摘要，未分发原始会话、机器路径或 session ID，不是可重放审计证据。当前安装仍需按版本/profile/插件核验。版本/profile/插件/权限变化时重新核对；不因重读 Skill 重复付费 probe。

| 调用 | 结论 |
|---|---|
| `subagent(run_in_background:false)` | 已通过：前台 one-shot，父收到最终文本。|
| `subagent(run_in_background:true)` | 已通过：当前配置返回真实 continuable child ID，并记录父 session/depth=1。|
| `list_agents({scope:"descendants"})` | 已通过：能列出 continuable 子 ID、父、深度、状态。|
| 对同一 child 调 `send_message` | 已通过：完成第二回合，不是重新创建。|
| settlement 通知 | 已通过：父收到真实回合结束通知。|
| 同时多成员负载、父跨进程续接、冷恢复、暂停/取消/关闭、桌面绑定 | 未实测；不从上项推断。|

第一次探测曾出现重复成员和工具冲突；复测用唯一任务键、一次创建约束及允许汇报工具完成。该结果不证明提示词能强制 exactly-once 或权限隔离，仍需登记真实 child、cwd、写集和产物。

## 当前环境核对

只读确认 `--version/--help/--profile headless --help` 和实际 home 下非 secret bundle/overlay。历史实现来自 `@deepseek-ai/dsh-base/cordis.patch.yml`，使用 `dsh-subagent` + `dsh-subagent-spawn-in-process`（backend `spawn`）、`dsh-tool-subagent`（`backgroundMode: continuable`）和 `dsh-tool-subagent-control`/`list-agents`；以当前真实 schema 为准，缺插件时报告阻塞，不擅自安装/patch。不得输出 `--dump-config` 全量或读取密钥文件。另行获准 probe 才在隔离 temp 跑合成任务，先判真实 gate，不做业务探测性修改。

## 部门如何调用成员

父会话先重新判 gate、检查 cwd/基线/写权，再调用：

```json
{
  "description": "TASK-001 contract worker",
  "prompt": "完整自包含任务卡：任务ID、目标/非目标、实际cwd、精确读写集、基线、接口版本、验收命令/负例、证据路径、budgetPolicy=unlimited、北京时间休息窗；不得递归委派；最多3行报告。",
  "run_in_background": false
}
```

前台文本不暴露 ID 时，从父 `subagent/catalog` 和子 header 核对，不能编造 ID。

需要后台 continuable 成员时改为 `true`，保存返回的真实 child ID。父可分别为 A/B 使用不相交写集创建多个成员：先记录 A 的 ID，再创建 B；不要声称同时负载已实测。父收到 settlement 后核对产物和测试，不能用 `message delivered`、`ready/idle` 或一次 `list_agents` 代替完成。

同一 child 增量返修：

```json
{
  "agent_id": "<真实直接 child ID>",
  "message": "新任务ID/基线/失败证据/修复范围/验收/变化约束；不得扩写集；最多3行报告。"
}
```

可按需调用 `list_agents({"scope":"descendants"})` 核对真实 ID 和状态，不忙轮询。运行时可能注入用 `send_message` 向父报告的要求，不能把“禁止一切工具”与此冲突；允许直接父级汇报不等于允许递归委派。`subagent-settled` 可能携带 reasoning，不能保证 runtime 通知也只有 3 行；完整 transcript 不会自动共享。

成员不继承父完整对话；不能只说“继续上面”。只向直接 child 发消息，不把另一部门主会话当成员，不向更深后代越级派发。部门汇报最多 7 行。

## 未验证项与禁止误用

当前后台模式为 `continuable`，其 child ID 不用 `job_output/job_kill`；one-shot 后台 jobs 分支未测。不要编造 `close_agent`、`wait_agent`、`--resume`，也不要把 Codex API 名称挪作 Harness API。源码中的 `interrupt_agent` 只表示请求取消当前回合，未证明销毁成员、停止子孙或成功取消；暂停窗不能靠它自称已强制。

`toolFilter`/`maxDepth` 是插件配置，不是上述 JSON 请求字段；任务卡不是技术沙箱。当前测试父子未调用文件/shell/network，不能推广为未来成员绝不会越权。发现重复 child 或越权时冻结受影响写权，登记全部真实 child/产物后处理。

不要擅自指定新模型；历史 descriptor 的 provider/model 只证明当次 route，不证明 HTTP endpoint。平台配额、时间 gate、写权、质量门和 Token 规则分别继承上级文件。