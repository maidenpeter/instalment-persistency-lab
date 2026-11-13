from streamlit.testing.v1 import AppTest

APP = "../app.py"
PAGE = "pages/5_Product_Levers_Simulator.py"


def _open():
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    at.switch_page(PAGE)
    at.run()
    assert not at.exception, at.exception
    return at


def _box(at, key):
    return next(w for w in at.number_input if w.key == f"{key}__box")


def _slider(at, key):
    return next(w for w in at.slider if w.key == f"{key}__slider")


def test_typing_a_value_moves_the_slider_and_back():
    at = _open()
    _box(at, "deposit").set_value(27).run()
    assert not at.exception, at.exception
    assert _slider(at, "deposit").value == 27
    _slider(at, "deposit").set_value(33).run()
    assert _box(at, "deposit").value == 33
    _box(at, "elasticity").set_value(0.6).run()
    assert abs(_slider(at, "elasticity").value - 0.6) < 1e-9


def test_instalments_box_moves_slider():
    at = _open()
    _box(at, "n_inst").set_value(10).run()
    assert _slider(at, "n_inst").value == 10


def test_run_applies_and_reset_restores():
    at = _open()
    _box(at, "deposit").set_value(30).run()
    at.button[0].click().run()  # Run scenario
    assert not at.exception, at.exception
    assert at.session_state["applied_levers"]["deposit"] == 30
    at.button[1].click().run()  # Reset levers
    assert not at.exception, at.exception
    assert _slider(at, "deposit").value == 20 and _box(at, "deposit").value == 20
    assert at.session_state["applied_levers"]["deposit"] == 20
