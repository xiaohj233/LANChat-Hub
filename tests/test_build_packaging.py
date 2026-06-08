import importlib.util
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_build_module():
    module_path = ROOT / "build_exe_py38.py"
    spec = importlib.util.spec_from_file_location("build_exe_py38", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_select_python38_falls_back_to_existing_venv(tmp_path):
    mod = load_build_module()
    venv_python = tmp_path / "venv2" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        if cmd == ["py", "-3.8", "--version"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not found")
        if cmd == [str(venv_python), "--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="Python 3.8.10\r\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="wrong candidate")

    selected = mod.select_python38(project_root=tmp_path, runner=fake_run)

    assert selected.command == [str(venv_python)]
    assert selected.version == "Python 3.8.10"


def test_write_password_runtime_hook_only_embeds_configured_values(tmp_path):
    mod = load_build_module()
    hook_path = tmp_path / "lanchat_build_passwords.py"

    mod.write_password_runtime_hook(
        hook_path,
        startup_password="boot-secret",
        admin_password_1="admin-one",
        admin_password_2="",
    )

    hook_text = hook_path.read_text(encoding="utf-8")
    assert "LANCHAT_STARTUP_PASSWORD" in hook_text
    assert "boot-secret" in hook_text
    assert "LANCHAT_ADMIN_PASSWORD_1" in hook_text
    assert "admin-one" in hook_text
    assert "LANCHAT_ADMIN_PASSWORD_2" not in hook_text


def test_write_spec_packages_static_without_git_or_sticker_exclusion(tmp_path):
    mod = load_build_module()
    spec_path = tmp_path / "console.spec"
    hook_path = tmp_path / "hook.py"

    mod.write_spec(spec_path, console=True, runtime_hook_path=hook_path)

    spec_text = spec_path.read_text(encoding="utf-8")
    assert "datas=[]" in spec_text
    assert "a.datas += Tree(str(STATIC_DIR), prefix='static'" in spec_text
    assert "telegram_stickers" not in spec_text
    assert "'.git'" in spec_text
