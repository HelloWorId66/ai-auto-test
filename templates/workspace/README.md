# 工作区：{project}

IFC AI 自动化测试的项目工作区（框架在单独的仓库，不在这里改）。

## 第一次使用（每个人本机各做一次）
1. 从 GitLab 拉取**框架仓库**，按其 README 准备 Python 环境（`python -m venv .venv`，安装 `playwright pyyaml`，执行 `python -m playwright install chromium`；Oracle 数据库检查再装 `oracledb`）。
2. 拉取本工作区。
3. 在 `config/local/<环境>.yaml` 填环境地址、账号、口令（该目录不入库）。可参考 `config/local/dev.yaml.example`。
4. 在 `workspace.local.yaml` 写 `framework: <本机框架目录>`（不入库）。
5. 运行 `python <框架目录>/ifc.py --workspace . doctor --login`，全部"通过"即可。
6. 在智能体（Claude Code、Codex 等）里打开本目录，用业务话说要测什么。

## 目录
- `scenarios/<模块>/<功能>/<场景>.yaml`：业务用例与审核记录（`*.review.yaml`）。未审核的用例不能正式运行。
- `reviews/`：给业务人员审核的 HTML 审核页。
- `results/`：运行结果（不入库）。`results/index.html` 是历史索引，每次运行单独一个批次目录，永不覆盖。
- `knowledge/`：模块知识、需求、环境观察、表单定义快照（`knowledge/forms`）。
- `bills/`、`probes/`、`extensions/`：单据状态模型、组件标定探针、本项目扩展。
- `.claude/skills/ifc-autotest/`：智能体规程（由 `ifc init --refresh` 从框架同步，勿手改）。
