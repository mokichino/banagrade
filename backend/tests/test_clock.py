from datetime import UTC, datetime

from app import clock


class FakeTime:
    CLOCK_REALTIME = 0

    def __init__(self) -> None:
        self.wall, self.since_boot = 1_000_000.0, 10.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.since_boot

    def clock_settime(self, _clock: int, value: float) -> None:
        self.wall = value

    def tick(self, seconds: float) -> None:
        self.wall += seconds
        self.since_boot += seconds


def test_watch_reports_only_a_big_forward_jump(monkeypatch) -> None:
    fake = FakeTime()
    monkeypatch.setattr(clock, "time", fake)
    watch = clock.ClockWatch()
    fake.tick(15)
    assert watch.check() is None
    fake.wall += 3  # an ordinary NTP correction
    fake.tick(15)
    assert watch.check() is None
    fake.wall -= 600  # stepped back: left to Storage, which keeps the current shift
    fake.tick(15)
    assert watch.check() is None

    before = fake.wall
    clock.set_clock(fake.wall + 3600)  # a phone's time, one hour ahead
    fake.tick(15)
    jump, cutoff = watch.check()
    assert jump == 3600
    assert cutoff == datetime.fromtimestamp(before + 15, UTC)  # everything stamped before the jump is at or before it
    fake.tick(15)
    assert watch.check() is None
