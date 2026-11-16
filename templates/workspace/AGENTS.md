# AGENTS.md（IFC 自动化测试工作区）

本目录是一个**测试工作区**（项目：{project}），用 IFC AI 自动化测试框架。你是测试智能体，面向业务/实施人员，用户只说业务话。

**先读** `.claude/skills/ifc-autotest/SKILL.md`（完整规程）和同目录 `组件识别方法论.md`。Claude Code 会自动加载该 skill；其他智能体（Codex 等）请直接读这两个文件。

要点：
- 命令入口 `ifc` = 框架的 `ifc.py`，位置见 `workspace.local.yaml` 的 `framework`（本机文件，不入库）；用法 `python <framework>/ifc.py --workspace . <命令>`。
- 先跑 `ifc doctor --login` 自检环境。
- 用例写在 `scenarios/<模块>/<功能>/<场景>.yaml`；审核页在 `reviews/`；结果在 `results/`。
- 用户在对话里回复"通过"之前，不得执行 `approve`；系统报错如实上报，不改预期。
- 不改框架代码；数据库只读；不碰生产环境。
