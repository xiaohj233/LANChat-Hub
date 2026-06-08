import main


def test_startup_password_loader_reads_environment(monkeypatch):
    monkeypatch.setenv("LANCHAT_STARTUP_PASSWORD", "boot-secret")

    assert main.load_startup_password() == "boot-secret"


def test_admin_passwords_prefer_environment_over_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("LANCHAT_ADMIN_PASSWORD_1", "admin-one")
    monkeypatch.setenv("LANCHAT_ADMIN_PASSWORD_2", "admin-two")
    monkeypatch.setattr(main, "ADMIN_PASSWORD_1", "")
    monkeypatch.setattr(main, "ADMIN_PASSWORD_2", "")
    monkeypatch.setattr(main, "CONFIG_FILE", str(tmp_path / "missing-config.json"))

    assert main.load_admin_passwords() == ("admin-one", "admin-two")
