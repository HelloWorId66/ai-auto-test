"""组件控件的 CSS 选择器表。

全部来自源码阅读（docs/exploration/01-组件全集.md），尚未在真实页面验证。
是否适用取决于环境和产品版本：必须先跑「选择器标定」，结果按（产品版本、项目、环境）记录在 calibration.py 的标定记录里。
"""
from __future__ import annotations

from typing import Dict, NamedTuple


class ControlSelector(NamedTuple):
    css: str
    evidence: str


CONTROL_SELECTORS: Dict[str, ControlSelector] = {
    "FormTextInput": ControlSelector("input.FormTextInput", "01 §2.1 FormTextInput.tsx:251,288"),
    "FormTextArea": ControlSelector("textarea", "01 §2.2 FormTextArea.tsx:335，id 为 compMark"),
    "FormNumberInput": ControlSelector(".osp-number-input input", "01 §2.3 FormNumberInput.tsx:353"),
    "FormDateField": ControlSelector(".osp-react-designer-pc-formDataField", "01 §2.4 FormDateField.tsx:487"),
    "FormComboBox": ControlSelector(".FormComboBoxComp", "01 §3.1 FormComboBox.tsx:454"),
    "HelpComboBox": ControlSelector(".FormComboBoxComp", "01 §3.2 HelpComboBox/index.tsx:952"),
    "FormCheckBox": ControlSelector(".ant-checkbox-group, .ant-checkbox-wrapper", "01 §4.1"),
    "FormSwitchButton": ControlSelector(".FormSwitchButton", "01 §4.3 FormSwitchButton.tsx:204"),
}

# 弹层与提示的稳定类名
POPUP_CALENDAR = ".PopupCalendar"
SELECT_ITEM = ".ant-select-item"
MODAL = ".ant-modal"


# IFC 业务组件（osp-react-department-webcomps）的外层容器类名是 compMark + '-container'，
# compMark = `${formID}-${key}-form`（RegisterWindowFun.js:2-14）。依据 docs/exploration/05-IFC业务组件.md。
COMPMARK_CONTAINER_TYPES = {
    "PaymentUnit",
    "InterestRateInput",
    "AccountOpenOrgan",
    "PaymentAccount",
    "CountryArea",
    "Currency",
}


def compmark_container_css(form_id: str, key: str) -> str:
    return f'[class~="{form_id}-{key}-form-container"]'
