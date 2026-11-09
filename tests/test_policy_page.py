from streamlit.testing.v1 import AppTest

PAGE = "../pages/7_Policy_Lookup.py"


def _run(at):
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def test_example_dropdown_loads_that_policy():
    at = _run(AppTest.from_file(PAGE, default_timeout=120))
    box = at.selectbox(key="example")
    target = box.options[-1]  # last example
    box.select(target)
    _run(at)
    assert at.text_input(key="policy_id").value in target


def test_typed_id_and_unknown_id():
    at = _run(AppTest.from_file(PAGE, default_timeout=120))
    at.text_input(key="policy_id").input("p019999")
    _run(at)
    at.text_input(key="policy_id").input("P999999")
    _run(at)
    assert any("No policy called P999999" in w.value for w in at.warning)
