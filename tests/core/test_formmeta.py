import json
import os
from pathlib import Path

import pytest

from ifcat.meta import FormMetaError, find_form_file, load_form, load_form_file

# 真实产品表单目录只在手上有的人才跑：IFCAT_REAL_FORMS_DIR=<目录>
REAL_DIR = Path(os.environ.get("IFCAT_REAL_FORMS_DIR", "/nonexistent"))


def _sample():
    return {
        "formID": "F1", "formName": "样例", "version": "React",
        "components": [{"key": "Root", "type": "FormBoxContainer", "props": {}, "children": [
            {"key": "A", "type": "FormTextInput", "props": {"showLabelText": "名称", "dataSetID": "T1", "dataSetColID": "F_NAME", "enableNotNull": True}},
            {"key": "B", "type": "FormTextInput", "props": {"showLabelText": "名称", "dataSetID": "T2", "dataSetColID": "F_NAME", "edit": False}},
            {"key": "TB", "type": "GridToolBar", "props": {"actionList": ["Act1", "Missing"]}},
            {"key": "G", "type": "AGGrid", "props": {"columnModel": "CM", "dataSetID": "!T2"}},
        ]}],
        "dataModels": [{"key": "Folder1", "type": "Folder", "children": [
            {"key": "CM", "type": "ColumnModel", "children": [
                {"key": "C1", "type": "Column", "props": {"headerText": "金额", "dataSetColID": "F_AMT", "editorType": "3"}}]}]}],
        "actionComps": [{"key": "Act1", "type": "GeneralAction", "props": {"actionText": "保存", "visibleExpression": "x"}}],
        "tableSource": [{"tableName": "主表", "tableID": "!T1"}],
    }


def test_fields_buttons_grids_from_synthetic():
    m = load_form(_sample())
    assert [f.key for f in m.fields] == ["A", "B"]
    assert m.fields[0].required is True and m.fields[0].editable is True
    assert m.fields[1].editable is False
    assert len(m.field_by_label("名称")) == 2
    assert m.field_by_label("名称", within="Root")[0].key == "A"
    assert [b.label for b in m.buttons] == ["保存"]  # 引用不存在的动作被忽略
    assert m.buttons[0].visible_expression == "x"
    assert m.grids[0].dataset_id == "T2"
    assert m.grids[0].columns[0].header == "金额"  # 列模型在 Folder 里也能找到
    assert m.datasets == {"T1": "主表"}


def test_invalid_form_raises():
    with pytest.raises(FormMetaError):
        load_form({"foo": 1})


def test_find_form_file_does_not_guess(tmp_path):
    with pytest.raises(FormMetaError):
        find_form_file("Nope", [tmp_path])
    (tmp_path / "X.json").write_text(json.dumps(_sample()), encoding="utf-8")
    assert find_form_file("X", [tmp_path]).name == "X.json"


@pytest.mark.skipif(not REAL_DIR.is_dir(), reason="未设置 IFCAT_REAL_FORMS_DIR")
def test_all_real_forms_parse_and_pilot_forms_shape():
    files = list(REAL_DIR.glob("*.json"))
    assert len(files) > 1000
    for p in files:
        load_form_file(p)
    m = load_form_file(REAL_DIR / "ZJ_DP_CorpDepPlacement_React.json")
    assert m.name == "企业存款存入_React"
    assert {"存款方", "起始日期", "到期指示"} <= {f.label for f in m.fields}
    assert {"保存", "提交", "同意"} <= {b.label for b in m.buttons}
    lm = load_form_file(REAL_DIR / "LM_BankCreditLimitUpdateForm.json")
    assert any(g.columns for g in lm.grids)
