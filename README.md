# IFC AI 自动化测试框架

业务人员用业务语言描述真实业务场景，智能体在 PanUI/OSP 系统上生成场景、跑回归并校对结果。业务人员只审业务场景和检查点，不审代码。
设计见 [docs/design/项目设计v3.md](docs/design/项目设计v3.md)。

## 框架与工作区

本目录只是**框架**，不含任何具体业务、项目或环境的内容，也不应因为新增业务而修改。
具体项目的东西全部放在**工作区**（独立目录，可单独入库）：

| 位置 | 放什么 | 谁可改 |
|---|---|---|
| 框架 `core/` | 受保护的公共操作库（Python 包 `ifcat`），只读、带版本、有完整性校验 | 仅维护者，经提案合入 |
| 框架 `tools/` `ui/` `templates/` `docs/` `tests/` | 辅助工具、本地运行页面、模板、通用文档、框架自测 | 维护者 |
| 工作区 `workspace.yaml` | 项目名、状态模型与探针清单、默认环境（可入库） | 项目人员 |
| 工作区 `workspace.local.yaml` | 本机路径，如框架所在目录（不入库） | 本机 |
| 工作区 `config/local/<环境>.yaml` | 环境地址、账号、界面语言、菜单路径；口令可直接写在该文件（测试环境内网；该目录不入库），也可用 `password_env` | 本机 |
| 工作区 `scenarios/` | 业务场景（YAML）及审核记录 `*.review.yaml` | 业务审核后入库 |
| 工作区 `bills/` `probes/` | 单据状态模型、组件标定探针 | 项目人员 |
| 工作区 `extensions/` | 本地扩展层（框架还没有的控件适配器、动作、数据库方言），不覆盖核心 | 项目人员 / 智能体 |
| 工作区 `knowledge/` `reviews/` `results/` | 模块知识、业务审核文字版、运行结果 | 项目人员 / 本机 |

找工作区的顺序：`--workspace <目录>`，环境变量 `IFCAT_WORKSPACE`，从当前目录向上找 `workspace.yaml`。

## 团队使用：分发与初始化

- **分发**：团队成员各自从 GitLab 拉取**框架仓库**和**项目工作区仓库**，按下文准备 Python 环境。只给智能体用的规程（`skills/ifc-autotest/`）也可单独发布到 SkillHub。
- **新项目**：`python ifc.py init <工作区目录> --project <项目名>` 生成工作区骨架，同时写入 `AGENTS.md`、`CLAUDE.md` 和智能体规程 `.claude/skills/ifc-autotest/`（Claude Code 自动加载；Codex 等读 `AGENTS.md` 指向的同一份）。框架升级后在工作区执行 `ifc init <目录> --refresh` 同步最新规程。
- **自检**：`python ifc.py --workspace <工作区> doctor --login`，检查 Python、浏览器、工作区、环境配置、环境可访问、账号登录，未通过项会写明怎么办。
- **智能体**：业务人员对 Claude Code、Codex 等智能体用业务话描述要测什么。规程让智能体自己连接知识库/测试库 MCP，不需要业务人员配置。

## 框架缺东西时：先在工作区补，定期归纳

做具体功能的人不改框架。遇到框架还不支持的控件或动作，在工作区 `extensions/` 里临时补上，先把当次工作做完；归纳和抽象由维护者定期做。

| 缺什么 | 在工作区怎么补 | 从哪里导入 |
|---|---|---|
| 一种控件（表单里的新组件类型） | 写一个 `Adapter` 子类，`type_name` 等于表单定义里的组件 type | `from ifcat.ext import Adapter` |
| 一个动作（如撤回、上传附件） | 写一个函数，用 `@action("名字", required=[...], text="业务说法", checkpoint=是否检查点)` 声明，返回 `StepResult` | `from ifcat.ext import action, StepResult` |
| 一种数据库（Oracle 以外） | `register_dialect("类型名", 连接工厂, readonly_begin="开启只读事务的语句")` | `from ifcat.ext import register_dialect` |

- 扩展只能新增，不能与框架自带的同名。扩展文件加载失败会在命令行明确提示。
- 用了扩展的场景，结果照常有效，报告里会标明「用到工作区扩展」。
- 维护者定期执行 `python ifc.py harvest <工作区>... [--out 清单.md]`，得到各工作区扩展的清单：所在文件、被多少场景引用、运行次数、通过次数，以及多个工作区重复出现的同名扩展。据此决定哪些并入框架。单个扩展也可以用 `python tools/propose.py` 主动提案。
## 用例必须先审核再运行

1. 智能体写场景，`ifc render <场景>` 生成 HTML 审核页（工作区 `reviews/<场景编号>.html`），页面写明场景目的、依据、前提、每步谁做什么、检查点，以及标红的「未确认」项。
2. 业务人员在浏览器里看审核页，在对话里回复「通过」或提出修改。通过后才执行 `ifc approve <场景>`，只在业务人员明确同意后执行。
3. `ifc run` 只运行已审核的场景；未审核的在报告里列为「未运行」。场景（包括它继承的基线场景）审核后只要有改动，审核自动失效，必须重新审核。
4. `--draft` 仅供开发调试，结果会标记为「未审核」，不能作为回归结论。

## 命令

```
python ifc.py init <目录> --project <项目名>                             # 生成工作区（--refresh 同步智能体规程）
python ifc.py --workspace <工作区> doctor [--login] [--env <环境>]        # 环境自检
python ifc.py --workspace <工作区> list [--module DP]                    # 场景与审核状态
python ifc.py --workspace <工作区> validate <场景>|--module DP|--all      # 离线校验，不连环境
python ifc.py --workspace <工作区> render <场景>|--module DP|--all        # 生成 HTML 审核页
python ifc.py --workspace <工作区> approve <场景>               # 记录业务审核
python ifc.py --workspace <工作区> run <场景>|--module DP,LM|--all --env <环境>   # 运行一个批次
python ifc.py --workspace <工作区> calibrate --env <环境>                 # 用真实页面标定组件适配器
python ifc.py harvest <工作区>... [--out 清单.md]                         # 维护者：汇总各工作区临时补的扩展
python ui/server.py --workspace <工作区>                                  # 本地运行页面
```

## 测试报告

每次 `run` 是一个批次，结果写入工作区 `results/runs/<项目>/<环境>/<批次>/`，批次之间永不覆盖：
- `report.html`：批次总览。通过、检查未通过、自动化未能完成、没有检查点、未运行的数量，和上一批次的对比（新增失败、已恢复），按模块分组，有问题的模块默认展开，可按结果筛选、搜索。
- `<场景>/report.html`：场景详情，每一步的结果和截图，检查点高亮，运行中取得的单据编号等。
- `results/index.html`：所有批次的历史索引，以及最近 10 次每个场景的状态点阵。
- 失败分两类：「检查未通过」只在检查点和预期不一致时出现，疑似产品问题，交业务或开发判断；「自动化未能完成」是步骤没能执行完（定位、等待、超时、环境、数据），出错时自动留页面截图，由智能体自行处理，不打扰业务人员。
- 报告只引用相对路径，把整个批次目录打包即可离线查看。

口令写在工作区 `config/local/<环境>.yaml`（该目录不入库，测试环境在内网），或用 `password_env` 指向环境变量；不写入场景、日志、报告。

## 范围与限制

- 只支持 React 表单。老式表单不在范围内。
- 界面语言由环境配置 `locale` 决定（默认 `zh-CN`）。菜单、按钮文字随语言变化（框架用到的按钮文字可用 `env_params.ui_text` 覆盖），标定记录绑定产品版本与语言。
- 数据库只读。数据库检查点（单据状态、结果表记录）需要在环境配置里给出只读账号；框架自带 Oracle，其他数据库在工作区用扩展接入。
- 场景数据里可用 `${today}` 系列日期变量和 `${unique}`（每次运行自动生成的 14 位不重复编号），避免写死日期、重复运行时数据撞车。
- 场景只能串行运行，没有并行和失败自动重跑。
- 浏览器默认直连（不走本机系统代理，否则内网地址可能 502）；确需代理时配置 `env_params.browser_proxy`。
- 已在 macOS 验证；Windows 尚未验证。

## 开发框架

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock      # 团队统一的依赖版本
.venv/bin/pip install -e .                      # 可选：安装后可以直接用 ifc 命令代替 python ifc.py
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest tests -q
```

- 只支持在框架仓库目录里安装（`pip install -e .`）：`ifc init` 要用到仓库里的模板和智能体规程。Windows 上把 `.venv/bin/` 换成 `.venv\Scripts\`。
- 核心库改动后，维护者必须升 `core/ifcat/__init__.py` 里的版本号，并运行 `python tools/release_manifest.py` 重新生成 `core/ifcat/MANIFEST.json`，否则入口拒绝运行。完整性校验用来发现无意的改动，不是安全机制；真正的把关是仓库的合并审核。
- 核心库版本变了，各环境要重新 `ifc calibrate`（标定记录绑定核心库版本）。
- 工作区 `workspace.yaml` 的 `framework_min_version` 写明它需要的框架最低版本，框架更旧时会提示先更新。

智能体规程见 [skills/ifc-autotest/SKILL.md](skills/ifc-autotest/SKILL.md)，组件识别方法见 [docs/组件识别方法论.md](docs/组件识别方法论.md)，写场景步骤见 [docs/agent-workflow.md](docs/agent-workflow.md)。
同级的旧工程仅供参考，不在本框架中使用。
