# IFC AI 自动化测试

业务人员用业务话说要测什么，智能体在 PanUI/OSP 系统的真实页面上写出用例、跑回归、核对结果。业务人员只审业务场景和检查点，不看代码。

## 它是怎么运转的

1. **用例是数据，不是脚本。** 一个业务场景写成一个 YAML 文件：谁、做什么、检查什么。引擎直接照着它操作页面。
2. **先审后跑。** 用例渲染成业务人员看得懂的审核页，业务人员说"通过"之后才能正式运行。用例一改，审核自动失效。
3. **三样东西分开放：**

| 是什么 | 在哪里 | 谁维护 |
|---|---|---|
| **技能**（规程 + 引擎） | 每个人电脑上安装的 `ifc-autotest` 技能 | 框架维护者发布，使用者只安装 |
| **工作区**（一个项目的用例、配置、结果） | 每个项目一个目录，可以入库 | 做具体功能的人 |
| **开发仓库**（本仓库） | 引擎源码、自测、打包工具 | 框架维护者 |

使用者只需要技能和工作区，**不需要本仓库**。

## 使用者：怎么用

1. 本机有 Python 3.10 或更高版本。
2. 安装 `ifc-autotest` 技能（从团队技能市场，或由维护者提供技能目录）。
3. 在智能体（Claude Code、Codex 等）里打开项目的工作区目录，用业务话说要测什么。没有工作区时智能体会帮你新建。

第一次使用时技能会自动准备运行环境（Python 依赖和浏览器，装在 `~/.ifc-autotest`，所有项目共用），需要几分钟和网络，只做一次。

技能里的规程见 [skills/ifc-autotest/SKILL.md](skills/ifc-autotest/SKILL.md)。

## 做具体功能的人：框架缺东西时

不改引擎，也不用等。在工作区 `extensions/` 里补上，先把当次工作做完：

| 缺什么 | 怎么补 |
|---|---|
| 一种控件 | 写一个 `Adapter` 子类 |
| 一个动作（如撤回、上传附件） | 写一个用 `@action` 声明的函数 |
| 一种数据库（Oracle 以外） | `register_dialect` 注册连接方式 |

写法见 [skills/ifc-autotest/references/排查与扩展.md](skills/ifc-autotest/references/排查与扩展.md)。用了扩展的场景结果照常有效，报告里会标明。

## 框架维护者

### 开发环境

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest tests -q
```

Windows 上把 `.venv/bin/` 换成 `.venv\Scripts\`。在仓库里直接运行引擎：`.venv/bin/python ifc.py <命令>`。

### 目录

| 位置 | 内容 |
|---|---|
| `core/ifcat/` | 引擎（受完整性校验保护） |
| `skills/ifc-autotest/` | 技能的源文件：规程 `SKILL.md`、按需阅读的 `references/`、启动脚本 `scripts/ifc.py` |
| `templates/workspace/` | 新建工作区时用的模板 |
| `tools/` | 辅助工具、打包和发版工具 |
| `ui/` | 本地运行页面 |
| `tests/` | 框架自测 |
| `docs/exploration/` | 当初对产品前端源码的分析笔记，供维护者参考，未逐条复核 |
| `docs/history/` | 早期设计文档，已过期，仅留作背景 |

### 发版

1. 改了 `core/ifcat/` 下的任何文件，都要升 `core/ifcat/__init__.py` 里的版本号，并运行 `python tools/release_manifest.py` 重新生成完整性清单，否则引擎拒绝运行。
2. 改了依赖版本，同步改 `requirements.lock`（运行用）和 `requirements-dev.lock`（开发用）。
3. 全部自测通过。
4. `python tools/build_skill.py` 生成 `dist/ifc-autotest/`。这个目录就是发给使用者的技能，里面有规程、引擎和启动脚本。
5. 把 `dist/ifc-autotest/` 发布到团队技能市场。本机试用：`python tools/build_skill.py --install ~/.claude/skills`。

版本变了之后，各环境要重新 `ifc calibrate`（标定记录绑定引擎版本）。工作区 `workspace.yaml` 的 `framework_min_version` 写明它需要的最低版本，技能太旧时会提示先更新。

完整性校验用来发现无意的改动，不是安全机制；真正的把关是仓库的合并审核。

### 定期归纳

各工作区临时补的扩展，定期汇总一次，决定哪些并入引擎：

```
python ifc.py harvest <工作区目录>... [--out 清单.md]
```

清单列出每个扩展所在的文件、被多少场景引用、运行次数、通过次数，以及多个工作区里重复出现的同名扩展。

## 范围与限制

- 只支持 React 表单。老式（GWT）表单不在范围内。
- 界面语言由环境配置的 `locale` 决定（默认 `zh-CN`）。引擎用到的按钮文字可以在环境配置的 `env_params.ui_text` 里覆盖。
- 数据库只读。引擎自带 Oracle，其他数据库在工作区用扩展接入。
- 场景只能一个一个运行，没有并行、失败自动重跑和单场景超时。
- 引擎里还有一部分等待是固定时长，环境很慢时可能不稳定。
- 流程动作里的取回、作废、加签、终止，引擎还没有自带，需要时在工作区扩展里补。
- 浏览器默认直连，不走本机系统代理（否则内网地址可能返回 502）；确实需要代理时配置 `env_params.browser_proxy`。
- 已在 macOS 上验证；Windows 尚未验证。
