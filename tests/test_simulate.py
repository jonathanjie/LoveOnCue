"""The gate's simulation script: its clock and the records raters score against."""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simulate

from wedding_ops.clock import parse_time


def run(directory: Path, *args: str) -> None:
    simulate.main(["--dir", str(directory), *args])


def test_the_realtime_clock_follows_real_time_and_advance_moves_it(tmp_path, monkeypatch):
    run(tmp_path, "init")
    run(tmp_path, "realtime")
    world = simulate.World(tmp_path)
    anchor = world.state["realtime"]
    start = parse_time(anchor["simulated"])
    world.close()

    # Ten real minutes later, the simulated clock is ten minutes on.
    later = parse_time(anchor["real"]) + timedelta(minutes=10)
    monkeypatch.setattr(simulate, "datetime", type("Fixed", (), {"now": staticmethod(lambda tz=None: later)}))
    world = simulate.World(tmp_path)
    assert world.clock.now() == start + timedelta(minutes=10)
    world.close()

    run(tmp_path, "advance", "5")
    world = simulate.World(tmp_path)
    assert world.clock.now() == start + timedelta(minutes=15)
    world.close()


def test_records_show_the_run_sheet_and_a_realistic_emergency_contact(tmp_path, capsys):
    run(tmp_path, "init")
    capsys.readouterr()
    run(tmp_path, "records", "--as", "usher")
    records = capsys.readouterr().out
    assert "18:30 Garden ceremony at Garden terrace" in records
    assert f"Emergency contact: {simulate.SIMULATED_EMERGENCY_CONTACT}" in records
    assert "Tasks of Jamie Lim:" in records and "What reached the coordinator from Jamie Lim:" in records
