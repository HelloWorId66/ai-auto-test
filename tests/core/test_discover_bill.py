import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("discover_bill", Path(__file__).resolve().parents[2] / "tools/discover_bill.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["discover_bill"] = mod  # dataclass 解析类型注解时需要
spec.loader.exec_module(mod)

OK = '''
/**
 * 演示流程
 */
public class DemoFlow extends FlowMovementAbstract {
    public FlowInitParam initParam() {
        FlowInitParam param = new FlowInitParam();
        param.setBillHeadTable("T_HEAD");
        param.setGuidField("F_GUID");
        param.setBillStatusField("F_ST");
        return param;
    }
}
'''
NULL = OK.replace("DemoFlow", "NullFlow").replace('setBillStatusField("F_ST")', "setBillStatusField(null)")


def test_extracts_three_elements_and_flags_null_status(tmp_path):
    (tmp_path / "MOD").mkdir()
    (tmp_path / "MOD/DemoFlow.java").write_text(OK, encoding="utf-8")
    (tmp_path / "MOD/NullFlow.java").write_text(NULL, encoding="utf-8")
    (tmp_path / "MOD/Other.java").write_text("public class Other {}", encoding="utf-8")
    found = {f.flow_no: f for f in mod.scan(tmp_path)}
    assert set(found) == {"DemoFlow", "NullFlow"}
    d = found["DemoFlow"]
    assert d.complete and d.module == "MOD" and d.title == "演示流程"
    assert d.fields["head_table"] == "T_HEAD" and d.fields["status_col"] == "F_ST"
    n = found["NullFlow"]
    assert not n.complete and n.status_null
    assert "显式设为 null" in mod.to_yaml(n, tmp_path)
