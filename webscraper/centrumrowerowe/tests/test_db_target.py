import pytest

import db


@pytest.mark.parametrize("url", [
    "sqlite:///cache.db",
    "postgresql+psycopg://biker:secret@localhost:5432/biker",
    "postgresql+psycopg://biker:secret@127.0.0.1:5433/biker",
    "postgresql+psycopg://biker:secret@[::1]:5432/biker",
])
def test_local_targets_pass_and_hide_password(url):
    shown = db.describe_target(url)
    assert "secret" not in shown


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://biker:secret@localhost:6543/biker",       # Cloud SQL proxy
    "postgresql+psycopg://biker:secret@10.1.2.3:5432/biker",
    "postgresql+psycopg://biker:secret@db.example.com/biker",
    "postgresql+psycopg://biker:secret@/biker?host=/cloudsql/proj:region:biker-pg",
])
def test_remote_targets_refused_unless_allowed(url):
    with pytest.raises(SystemExit) as exc:
        db.describe_target(url)
    assert "secret" not in str(exc.value)
    assert "secret" not in db.describe_target(url, allow_remote=True)


def test_check_target_on_temp_sqlite(temp_db):
    assert temp_db.check_target().startswith("sqlite")
