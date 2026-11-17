# 工作区：{project}

IFC AI 自动化测试的项目工作区：本项目的用例、配置和结果都在这里。

## 第一次使用（每个人本机各做一次）
1. 安装 `ifc-autotest` 技能（团队技能市场）。本机需要有 Python 3.10 或更高版本。
2. 拉取本工作区。
3. 复制 `config/local/dev.yaml.example` 为 `config/local/dev.yaml`，填环境地址、账号、口令（该目录不入库）。
4. 在智能体（Claude Code、Codex 等）里打开本目录，用业务话说要测什么。第一次会自动准备运行环境，需要几分钟。

想自己确认环境是否可用：`python <技能目录>/scripts/ifc.py doctor --login`，全部"通过"即可。

## 目录
- `scenarios/<模块>/<功能>/<场景>.yaml`：业务用例与审核记录（`*.review.yaml`）。未审核的用例不能正式运行。
- `reviews/`：给业务人员审核的 HTML 审核页。
- `results/`：运行结果（不入库）。`results/index.html` 是历史索引，每次运行单独一个批次目录，永不覆盖。
- `knowledge/`：模块知识、需求、环境观察、表单定义快照（`knowledge/forms`）。
- `bills/`、`probes/`：单据状态模型、组件标定探针。
- `extensions/`：框架还没有的控件适配器、动作，在这里临时补上先完成工作；框架维护者会定期归纳。
