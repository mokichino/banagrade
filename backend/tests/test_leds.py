from app.leds import LedController, LedState


class FakeLed:
    def __init__(self) -> None:
        self.mode = "off"

    def on(self) -> None:
        self.mode = "on"

    def off(self) -> None:
        self.mode = "off"

    def blink(self, on_time: float, off_time: float, n=None) -> None:
        self.mode = f"blink:{on_time}"

    def close(self) -> None:
        pass


def _controller():
    outputs = {color: FakeLed() for color in ("green", "yellow", "blue", "red")}
    changes: list[LedState] = []
    return LedController(changes.append, outputs), outputs, changes


def test_thesis_colour_mapping() -> None:
    controller, out, changes = _controller()
    controller.set(LedState.READY)
    assert out["green"].mode == "on" and out["red"].mode == "off"
    controller.show_grade("Class A")
    assert out["yellow"].mode == "on" and out["green"].mode == "off"
    controller.show_grade("Class B")
    assert out["blue"].mode == "on" and out["yellow"].mode == "off"
    controller.show_grade("Rejected")
    assert out["red"].mode == "on"
    assert changes == [LedState.READY, LedState.CLASS_A, LedState.CLASS_B, LedState.REJECTED]


def test_slow_and_fast_red_blink() -> None:
    controller, out, _ = _controller()
    controller.set(LedState.ERROR)
    fast = out["red"].mode
    controller.set(LedState.BOOTING)
    slow = out["red"].mode
    assert fast.startswith("blink") and slow.startswith("blink")
    assert float(fast.split(":")[1]) < float(slow.split(":")[1])


def test_unknown_grade_signals_error_and_no_hardware_is_safe() -> None:
    controller = LedController()
    controller.show_grade(None)
    assert controller.state is LedState.ERROR
    assert controller.status()["hardware_available"] is False


def test_gpio_is_off_by_default_and_state_still_tracked(monkeypatch) -> None:
    monkeypatch.delenv("BANAGRADE_ENABLE_GPIO", raising=False)
    changes = []
    controller = LedController(changes.append)
    controller.open()  # must not touch gpiozero
    controller.show_grade("Class B")
    status = controller.status()
    assert status["mode"] == "software" and status["gpio_enabled"] is False
    assert status["hardware_available"] is False and status["error"] is None
    assert changes == [LedState.CLASS_B]
