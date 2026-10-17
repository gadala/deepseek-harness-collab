# 项目适配与真实 CLI 入口

仅在首次接入项目、认证异常或环境变化时读取。

## 只读发现

按当次机器和项目发现并核对：项目根、既有任务板/工作流、当前 HEAD 与脏文件、依赖/脚本、测试命令、实际 `DSH_HOME`、Harness 安装、可用 node/dsh 入口、profile、认证状态、平台配额和当前 cwd。用 `git rev-parse --show-toplevel`、`git rev-parse HEAD`、`git status --porcelain` 核对；多机器/checkout/远端按当批授权和 hash 验证。先看环境变量，未设置 `DSH_HOME` 再按 launcher/PATH/实际安装目录发现；不要假定 `.dsh` 或历史路径。

优先发现官方 CLI launcher（Windows 打包安装可查 `resources/runtime/cli/bin/dsh.cmd`），核对其真实 runtime/入口；`resources/node/node.exe`、`resources/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js` 仅作其他发行结构线索，不假定一定存在。用户指定模型或官方直连时核对真实非 secret route/endpoint 或调用证据；descriptor 名字和 README 不证明官方直连。

不打印完整环境、secret、全量配置或凭据。只保留版本、profile、必要 bundle/plugin 名和脱敏错误。不要为认证自动启动桌面、寻找授权 URL、探测 session API 或修改配置。

## 部门入口

确认授权、写集、time gate、跨窗检查点后：

```powershell
Set-Location -LiteralPath $authorizedWorkDir
$LASTEXITCODE = $null
& $dshLauncher --profile headless $departmentTask
$code = $LASTEXITCODE
```

`$dshLauncher/$authorizedWorkDir/$departmentTask` 必须来自当次核对；完整任务卡自包含。没有 launcher 时可用已核验的独立 Node 执行 `& $nodeExe $dshBin --profile headless $departmentTask`；Electron 打包入口则需其原有 `ELECTRON_RUN_AS_NODE=1` 和 `--expose-internals` 启动约定，环境仅限子进程，不把 exe 当普通 Node 盲调。SSH/Git 可交付和同步代码，但不是任务发送通道。部门主会话输出后退出，不当作常驻服务；无经过验证的 `--resume` 就用新会话加交接包。实际 workspace 不保证被 cwd 覆盖，须看 profile/日志/产物。

## 执行通道故障与获准本地修复

`0xC0000142` 空输出不能归咎于任务命令，也不能因文件工具正常就排除执行 sandbox。先对照只读/可写模式、PID、原生 runner 与无害命令，区分进程创建和初始化；失败不自动提权、关闭 sandbox 或换桌面路线。

本项目不分发本机专用的执行通道补丁或修复 launcher。若部署环境已有用户批准的修复入口，仅在版本、目标模块路径和 SHA-256 全部匹配、且无害执行与边界负例通过后使用；没有这些证据时保持阻塞并报告。不要从历史文档推断当前机器需要相同补丁，也不要降低 sandbox 或自动提高权限。

版本、模块路径或 hash 变化立即停用并重新核验；hook 只对已知路径校验 hash，路径改名不能当作兼容。不得在失配后偷偷绕回旧入口或无限制模式。修复仅作用于此 launcher 的新 CLI 进程，不修复既有桌面/主会话；不能凭一个父会话通过就宣称多部门和所有子 agent 均验收。

## 项目写权与自修改

项目既有任务板和写权是真相，不另造长期业务账本。精确列出读/写路径；不使用宽泛 glob。保留他人脏改，只回退本批。worker 默认不操作共享 index，不 `add/commit/stash/reset/clean`；部署、push、重启、线上回退各自授权。

编辑本 Skill 本身只有在用户明确授权时进行；不得把修改 Skill 的权限推广到业务源码。外部日志/配置/worker 输出均需核验。

外部 Harness 实施不等于启用项目运行时自修改；保持自修改、自动发布和守护原开关，启用需单独授权。Skill 不新增持久守护、排程或自动执行器。push/远端 hook/工作树更新只证明代码同步；分别验证推送结果、目标 HEAD/工作树和服务实际加载版本，不推断运行态已更新。
