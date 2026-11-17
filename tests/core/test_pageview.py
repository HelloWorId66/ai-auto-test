"""文本框按输入框 id 定位、只看不动的表单查看：用假页面，不连环境。"""
from ifcat.adapters import build_default_registry
from ifcat.locator import find_field_root
from ifcat.meta import load_form
from ifcat.pageview import field_lines, option_lines

FORM = load_form({
    "formID": "F1", "formName": "演示", "version": "React",
    "components": [{"key": "Root", "type": "FormBoxContainer", "props": {}, "children": [
        {"key": "A", "type": "FormTextInput", "props": {"showLabelText": "合同编号", "dataSetID": "T1", "dataSetColID": "F_A"}},
        {"key": "B", "type": "FormTextInput", "props": {"showLabelText": "隐藏项", "dataSetID": "T1", "dataSetColID": "F_B"}},
    ]}],
    "dataModels": [], "actionComps": [],
    "tableSource": [{"tableName": "主表", "tableID": "!T1"}],
})


class Loc:
    def __init__(self, n=0, value="", disabled=False, visible=True):
        self.n, self.value, self.disabled, self.visible = n, value, disabled, visible
        self.first = self

    def count(self):
        return self.n

    def locator(self, _):
        return self

    def is_visible(self):
        return self.visible

    def input_value(self):
        return self.value

    def is_disabled(self):
        return self.disabled

    def get_attribute(self, _):
        return None


class Page:
    """只有「合同编号」的输入框带 id；没有任何组件容器标记，也没有 FormTextInput 类名。"""

    def __init__(self):
        self.asked = []

    def locator(self, css):
        self.asked.append(css)
        if css == 'input[id="F1-A-form"], textarea[id="F1-A-form"]':
            return Loc(1, "HT-001")
        return Loc(0)

    def evaluate(self, *_):
        return {"found": False, "labelHits": 0, "rootHits": 0}


def test_editable_text_input_is_located_by_input_id_not_class_name():
    page = Page()
    root = find_field_root(page, FORM, FORM.field_by_label("合同编号")[0])
    assert root.input_value() == "HT-001"
    assert not any("input.FormTextInput" in css for css in page.asked)


def test_view_lists_fields_without_touching_the_page():
    page = Page()
    lines = field_lines(page, FORM, build_default_registry())
    assert lines[0].split("\t") == ["合同编号", "FormTextInput", "", "可填", "HT-001"]
    assert "页面上没找到" in lines[1]


class OptRoot:
    """一个可填的下拉字段。"""

    def __init__(self, page):
        self.page, self.first = page, self

    def count(self):
        return 1

    def is_visible(self):
        return True

    def locator(self, css):
        if "disabled" in css:
            return Loc(0)
        return Trigger(self.page) if "ant-select-selector" in css else self


class Trigger(Loc):
    def __init__(self, page):
        super().__init__(1)
        self.page = page

    def click(self):
        self.page.open = True


class Popup:
    def __init__(self, page):
        self.page, self.last = page, self

    def count(self):
        return 1 if self.page.open else 0

    def is_visible(self):
        return self.page.open

    def evaluate(self, _):
        return {"heads": ["编号", "名称"], "items": ["A001 甲公司", "A002 乙公司"]}


class Keyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key):
        self.page.keys.append(key)
        self.page.open = False


class OptPage:
    def __init__(self):
        self.open, self.keys, self.keyboard = False, [], Keyboard(self)

    def locator(self, css):
        if "ant-select-dropdown" in css:
            return Popup(self)
        return OptRoot(self) if "F1-A-form" in css else Loc(0)

    def evaluate(self, *_):
        return {"found": False, "labelHits": 0, "rootHits": 0}

    def wait_for_timeout(self, _):
        pass


def test_options_are_listed_and_the_popup_is_closed_without_choosing():
    page = OptPage()
    lines = option_lines(page, FORM)
    assert lines == ["合同编号（列：编号、名称）\tA001 甲公司；A002 乙公司"]
    assert page.keys == ["Escape"] and not page.open
