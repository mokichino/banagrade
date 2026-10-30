import importlib.util
from pathlib import Path

from app.storage import Storage, now_iso

spec = importlib.util.spec_from_file_location("clear_scans", Path(__file__).resolve().parents[1] / "scripts" / "clear_scans.py")
clear_scans = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clear_scans)


def _setup(tmp_path: Path) -> tuple[Storage, list[str]]:
    storage = Storage(tmp_path / "banagrade.db")
    storage.initialize()
    session = storage.ensure_active_session()
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "a.jpg").write_bytes(b"\xff\xd8jpeg")
    storage.save_scan({"scan_id": "a", "session_id": session["id"], "captured_at": now_iso(), "final_grade": "Class A", "processing_status": "completed", "image_refs": [str(frames / "a.jpg")]})
    args = ["--db", str(storage.path), "--backups", str(tmp_path / "backups"), "--frames", str(frames)]
    return storage, args


def test_clear_needs_clear_typed(tmp_path, monkeypatch, capsys) -> None:
    storage, args = _setup(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt: "clear")
    assert clear_scans.main(args) == 1
    assert "Nothing deleted." in capsys.readouterr().out
    assert len(storage.list_scans()) == 1


def test_clear_backs_up_and_keeps_the_photos(tmp_path, monkeypatch, capsys) -> None:
    storage, args = _setup(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt: "CLEAR")
    assert clear_scans.main(args) == 0
    out = capsys.readouterr().out
    assert "1 scan in 1 shift." in out and "Cleared 1 scan, 0 disputes and 0 past shifts; moved 1 photo into the backup." in out
    assert storage.list_scans() == []
    [folder] = (tmp_path / "backups").iterdir()
    assert (folder / "banagrade.db").is_file() and (folder / "frames" / "a.jpg").is_file()


def test_clear_refuses_a_missing_database(tmp_path, capsys) -> None:
    assert clear_scans.main(["--db", str(tmp_path / "nope.db"), "--yes"]) == 1
    assert not (tmp_path / "nope.db").exists()
