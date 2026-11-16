"""工作区扩展的公开接口。扩展文件只从这里导入，框架内部结构调整不影响已有扩展。

- Adapter：新增一种控件的操作方式（type_name 等于表单定义里的组件 type）。
- action：新增一个动作，见 actions.py。
- register_dialect：接入 Oracle 以外的数据库（如信创库）的只读连接。
"""
from . import flowops, waits  # noqa: F401
from .actions import ActionContext, action  # noqa: F401
from .adapters import Adapter  # noqa: F401
from .dbro import register_extension_dialect as register_dialect  # noqa: F401
from .result import BlockedError, StepResult  # noqa: F401

__all__ = ["ActionContext", "Adapter", "BlockedError", "StepResult", "action", "flowops", "register_dialect", "waits"]
