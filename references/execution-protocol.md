# 批次执行协议（按需）

用于多 writer、重复派发风险、换代或 unknown 恢复；普通单部门一次性只读任务不强制增加 JSON 往返。此协议扩展既有批次执行登记，不建立第二套项目任务板。

## 工具与边界

`scripts/execution_protocol.py` 仅使用 Python 标准库：原子登记、路径/资源冲突校验、证据 hash、状态校验和短交接。**不启动模型、自动重试、续接/关闭 agent，不证明进程停止，不认证报告人，不执行测试，不是沙箱。** Codex 写控制登记和独立验收附件；worker 只写获准业务与自测证据。输入/输出禁止 secret、认证配置或授权 URL。证据 hash 只证明读取时完整性，不证明内容真实。

批次 JSON 存在项目获准审计路径，不能进入 worker 写集。每个真实 writer 一条任务，精确文件包含生成物/日志；部门协调者若有自写范围，不能与成员相交。不要先锁部门的全体写集、再锁重叠成员写集：协调者仅锁自己写集，成员逐个锁获准分配。父子归属和每个真实 child 登记在部门 runtime；未取得真实 ID 用 null，不造 ID。续接、成员启动仍每次重新判时间，父的 gate 不能代替成员的 gate。

现版保守拒绝活跃 writer 与其他读者重叠；稳定共享接口先用受控快照，只读快照精确路径加入 readSet。跨 cwd 的读取同样比较绝对路径；不把它当读权限沙箱。worktree 不隔离进程、Git 公共资源、端口或数据库；共享资源用显式资源键，同项目采用一致命名，例如 `tcp:3000`。

## 输入约定

`snapshot.json`：

```json
{"baseline":"实际 HEAD+脏改动摘要或受控基线指纹","interfaces":{"api":"实际 hash/version"}}
```

这里的 snapshot 是 Codex 核对后的值，工具不自动发现 HEAD/所有接口。`reserve` 会 hash 本包 readSet/writeSet，`preflight` 复核启动前变化；其他相关依赖必须纳入读集或接口指纹。基线测试失败也保留证据及风险，不能因新登记覆盖。

`task.json`（动态值由 Codex 填，路径可为 cwd 内相对文件；不能使用目录/通配符，授权来自人和项目约束而非 JSON）：

```json
{
  "schemaVersion":1,"taskId":"PKG-1","attemptId":"PKG-1-try1",
  "department":"implementation","cwd":"F:/authorized/project",
  "goal":"窄工作包及完成定义","nonGoals":["部署"],
  "readSet":["contract.snapshot.json"],"writeSet":["src/module.py","evidence/worker.log"],
  "snapshot":{"baseline":"实际基线","interfaces":{"api":"实际版本"}},
  "dependencies":[],"resources":[],"risks":[],"unknowns":[],
  "checks":["worker","scope","negative","contract","independent","integration"],
  "permissions":{"gitIndex":false,"deploy":false,"recursiveDelegation":false}
}
```

`checks` 是本包必须保留的质量门，可增补具体名称；验收命令、负例、完成定义仍在自包含任务资料包中，不能只列名字。只读/非代码任务按任务性质提供独立检查流程，不能伪造测试命令；任何必要步骤跑不了保持未验收。记录部署/Git index 授权不意味着脚本允许或执行这些操作，默认仍 false。成员默认不得递归委派；授权部门可建立直接成员，由 Codex/获准部门明确分配，成员任务不包含转授权。

## 操作顺序

```powershell
$tool = Join-Path $skillRoot 'scripts/execution_protocol.py' # skillRoot 按当前安装发现
python -B -X utf8 $tool init --registry $batchJson --record $snapshotJson
python -B -X utf8 $tool validate --record $taskJson
python -B -X utf8 $tool reserve --registry $batchJson --record $taskJson
python -B -X utf8 $tool preflight --registry $batchJson --record $idsJson
# 仅退出码 0，立即按 SKILL.md 的实际 headless CLI 入口派发；不把这个结果当未来许可。
```

`ids.json` 为 `{"taskId":"PKG-1","attemptId":"PKG-1-try1"}`。首次 `preflight` 登记一次启动检查，重复调用拒绝：若输出丢失/尚未启动，先核证，再记录 failed/not_started 并 release；新 attempt 带 retryReason、重新授权。不是自动补发。真实调用刚好跨时间边界仍需临近重查 time gate；脚本无法拦截 Harness 内部模型请求。现有 running 回合的 preflight 仅重查已登记约束和时间，不证明父/子还活着、不赋予原生恢复能力；续接投递未知须 update 为 unknown，不能当成可重发。

实际启动后用 `update --record lifecycle.json`；它记录观察事实，不作为派发入口，在休息时段也可登记已发生的启动/收尾。`receipt --path 文件` 输出 `{path,sha256}`，所有证据必须存在且 hash 匹配。

生命周期记录：

```json
{
  "taskId":"PKG-1","attemptId":"PKG-1-try1","phase":"running",
  "process":"running","descendants":"unknown","exitCode":null,
  "runtime":{"handle":"真实 exec 句柄","sessionId":null,"children":[]},
  "evidence":{"path":"绝对脱敏证据路径","sha256":"实际 SHA256"},
  "risks":[],"unknowns":[]
}
```

- `runtime.children` 保存**所有已见真实 child**，不得丢掉旧 ID；父 session 首次未知可为 null，取得真实 ID 后固定；exec handle 一旦登记不得换成新实例。停止证明需覆盖此集合，新实例使用新 attempt，不冒充原生 resume。
- 合法阶段：reserved → running/unknown/delivered/failed；真实 one-shot 直接完成时用 runtime/退出证据登记 delivered，不虚构中间 running；running → running/unknown/delivered/failed；unknown 经查证 → running/unknown/delivered/failed。仅创建 reserved 时进程状态为 unknown（任务登记不证明未启动）。
- delivered/failed 需实际 parent stopped/not_started、descendants stopped/none 的证据；delivered 还需真实退出码 0。**无输出、超时、Transport closed、idle 都不能证明这些值。** 缺失证据保持 unknown，占用不释放。
- 观察新增风险/未知必须保留；移除旧条目必须附 resolution 并由证据支持。短报告不得省掉它们。

## 验收、释放与失效

Codex 独立执行检查后，`accept --record acceptance.json`。附件必须含 `schemaVersion:1`、taskId/attemptId、当前 snapshot、`reviewer:"codex"`、`artifacts:[{path,sha256}]`、risks/unknowns、checks：

```json
{"name":"negative","command":"实际命令或人工核查流程","exitCode":0,
 "performedBy":"codex","evidence":{"path":"绝对证据路径","sha256":"实际 SHA256"}}
```

所有 task.checks 都须有零退出码/完整证据；worker 项来自 worker，其余来自 Codex 独立检查。unknown 不得接受，已有风险须带入，不允许自测代替验收。手动核查只有真正完成且留证后才能用 exitCode 0 表示；无证据不能编造。

`accept` 只是登记 Codex 已完成验收的证据；字段 `reviewer` 不是身份认证。实际验收责任仍属 Codex。本包 integration 指当前实际消费者/集成状态检查；整个批次完成后，仍须在最终实际组合上重跑回归，不能用分包 acceptance 宣称全项目通过。

`release --record release.json` 输入 taskId/attemptId/evidence，仅在真实 parent 及子孙停止、已 delivered/failed 后释放；进程结束与 acceptance 分开，未验收也可安全收尾但不能成为下游已通过依赖。新 attempt 必须有 retryReason，旧记录不覆盖。

`refresh --record snapshot.json` 用于 Codex 确认基线/接口改变后刷新，**不释放占用**。旧 snapshot、read/write 文件或证据 hash 变化，使旧 accepted 在检查时变 stale；上游失效使下游验收失效。拒绝把旧 pass 当成当前通过。dependency 必须是当前 accepted 且 released 才能启动消费者；依赖文件不能悄悄漏出读集。

## 简报与交接

- `summary --registry ...`：默认先读此短状态，不读完整历史。
- `handoff --registry ...`：最新 attempt 的目标/非目标、验收项、基线/接口、读写集/资源、权限、证据、运行态、风险/unknown 和历史索引；完整日志/旧任务留登记文件。
- `validate-handoff --registry ... --record handoff.json`：检查与当前登记一致，缺字段或陈旧则拒绝。保存 JSON 显式 UTF-8，勿把工具输出包装成另一层 JSON。
- `inspect`：完整登记，只用于必要排障/审计，不例行灌入上下文。

交接不是授权继承：新实例必须重新核基线、权限、真实进程和资源。成员 ≤3 行、部门 ≤7 行继续有效，简报引用附件而非复制 JSON/日志。无需为协议检查再开模型会议。

注册变更使用独占创建 `.lock` + 同目录原子 replace。锁忙/崩溃遗留时退出 2，不轮询、不按年龄删除；先确认 owner 已停止，人工处理当前登记锁，**不能顺便释放任务写权**。仅适用于本机可靠文件系统，非分布式锁。共享模型配额、429、有限重试等旧规则不变。

所有成功动作退出 0，阻塞/无效输入退出 2；失败输出 JSON，不展示认证或环境。CLI 没有 --at 绕过生产判时入口。测试用临时文件和虚拟证据验证检查器，不是 Harness 真实并发或效果测量。
