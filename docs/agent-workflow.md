# 智能体工作规程：用框架写场景

完整规程（含用户定义的端到端流程、结果判读、排查顺序）见 `skills/ifc-autotest/SKILL.md`，本文件是其中"写场景"一节的细化。

场景是 YAML 数据，不是代码。业务人员审的是渲染出的文字版。所有新增内容只写进**工作区**，不改框架。

## 写一个新场景
1. 确认业务和流程：读工作区 `knowledge/modules/README.md` 的接入步骤，需求放 `knowledge/requirements/`。没有证据（代码、配置、实际界面、业务确认）的内容标「未确认」，不推断。
2. 状态模型：`python tools/discover_bill.py` 生成骨架，写入工作区 `bills/*.bills.yaml` 并在 `workspace.yaml` 的 `bills` 登记，结果表需读 `processSubmitToEnd` 补充。
3. 复制框架 `templates/新场景.yaml` 到工作区 `scenarios/<模块>/`，只用 `STEP_SPECS` 里的动作和工作区扩展动作。字段标签必须取自表单定义。
4. 每个场景至少一个检查点（`expect_*`）。只写核心生产场景（含必要的核心异常），不写边界值和冒烟。
5. 离线校验：`python ifc.py --workspace <工作区> validate <场景>`。
6. 生成 HTML 审核页：`python ifc.py --workspace <工作区> render <场景>`。场景里要填 `goal`（保证什么）、`source`（依据）、`unconfirmed`（没证据的内容）、`labels`（技术字段名对应的业务名称）。**把审核页交给业务人员，等待对话里的明确答复**。
7. 业务人员明确通过后才 `approve`。智能体不得自行审批。

## 增量需求
新建场景文件，`extends` 基线场景，用 `set`、`add_steps_after`、`remove_steps` 表达。先跑受影响的主线，再加新字段检查点。基线或增量场景任一被改动，审核即失效，需要重新审。

## 运行与标定
- 首次在新环境、新产品版本、新界面语言上：`python ifc.py --workspace <工作区> calibrate --env <环境>`，探针用没有业务副作用的字段。
- 运行：`run <场景>` 或 `run --module DP,LM` 或 `run --all`，加 `--env <环境>`；也可用 `python ui/server.py --workspace <工作区>`。单个场景未审核或审核后改动会被拒绝（退出码 3）；批量运行时这类场景记为「未运行」。
- 每次运行生成批次报告（HTML），见 README「测试报告」。
- `--draft` 只用于开发调试，结果标「未审核」，不能当回归结论。
- `blocked`（自动化未能完成）是脚本、定位、环境、数据问题，**智能体自己处理，不要为此打扰业务人员**；`failed`（检查未通过）是系统行为和预期不一致，不要改预期放过，如实报告；`invalid` 表示没有检查点。

## 边界
- 数据库只读；口令写在工作区 `config/local/<环境>.yaml`（不入库）或用 `password_env`，不进场景、日志、结果。
- 不修改框架 `core/`。缺控件适配器或缺动作时在工作区 `extensions/` 新增（见 README「框架缺东西时」），先完成当次工作；并入框架由维护者定期用 `ifc harvest` 归纳，也可以用 `python tools/propose.py` 主动提案。
- 只支持 React 表单。
- 登录方式、菜单路径、状态值没有真实页面证据前不写死，向用户确认或自己探查真实页面。
