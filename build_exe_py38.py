#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build LANChat Hub EXE files with Python 3.8 and bundled static assets."""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
STATIC_DIR = PROJECT_ROOT / "static"
STICKER_DIR = STATIC_DIR / "telegram_stickers"
BUILD_HELPER_DIR = PROJECT_ROOT / "build" / "lanchat_packaging"

EXE_CONSOLE = DIST_DIR / "聊天室.exe"
EXE_NOCONSOLE = DIST_DIR / "聊天室无命令行.exe"


@dataclass
class PythonSelection:
    command: List[str]
    version: str


def _run_version_probe(
    command: List[str],
    project_root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
) -> Optional[str]:
    result = runner(
        command + ["--version"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode == 0 and output.startswith("Python 3.8"):
        return output.splitlines()[0]
    return None


def _python38_candidates(project_root: Path) -> Iterable[List[str]]:
    yield ["py", "-3.8"]

    for rel_path in (
        "venv2/Scripts/python.exe",
        "venv_win7/Scripts/python.exe",
        "venv1/Scripts/python.exe",
    ):
        python_path = project_root / rel_path
        if python_path.exists():
            yield [str(python_path)]

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        python_path = Path(local_appdata) / "Programs" / "Python" / "Python38" / "python.exe"
        if python_path.exists():
            yield [str(python_path)]


def select_python38(
    project_root: Path = PROJECT_ROOT,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> PythonSelection:
    for command in _python38_candidates(project_root):
        try:
            version = _run_version_probe(command, project_root, runner)
        except FileNotFoundError:
            continue
        if version:
            return PythonSelection(command=command, version=version)

    raise RuntimeError(
        "Python 3.8 was not found. Install/register Python 3.8, or restore a local 3.8 venv."
    )


def run_command(command: List[str], cwd: Path = PROJECT_ROOT) -> None:
    print("> " + " ".join(command))
    result = subprocess.run(command, cwd=str(cwd), check=False)
    if result.returncode != 0:
        raise RuntimeError("Command failed with exit code %s" % result.returncode)


def check_pyinstaller(selection: PythonSelection) -> None:
    result = subprocess.run(
        selection.command + ["-m", "PyInstaller", "--version"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "PyInstaller is not installed for %s. Install it in that Python 3.8 environment."
            % " ".join(selection.command)
        )
    print("PyInstaller: %s" % (result.stdout or result.stderr).strip())


def write_password_runtime_hook(
    hook_path: Path,
    startup_password: str = "",
    admin_password_1: str = "",
    admin_password_2: str = "",
) -> None:
    passwords = {}
    if startup_password:
        passwords["LANCHAT_STARTUP_PASSWORD"] = startup_password
    if admin_password_1:
        passwords["LANCHAT_ADMIN_PASSWORD_1"] = admin_password_1
    if admin_password_2:
        passwords["LANCHAT_ADMIN_PASSWORD_2"] = admin_password_2

    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(
        "import os\n\n"
        "_PASSWORDS = %s\n\n"
        "for key, value in _PASSWORDS.items():\n"
        "    os.environ[key] = value\n" % json.dumps(passwords, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )


def _hiddenimports_text() -> str:
    imports = [
        "flask",
        "werkzeug",
        "werkzeug.debug",
        "werkzeug.serving",
        "sqlite3",
        "hashlib",
        "uuid",
        "mimetypes",
        "json",
        "logging",
        "datetime",
        "socket",
        "re",
        "subprocess",
        "html",
        "tkinter",
    ]
    return "[\n%s\n    ]" % "".join("        %r,\n" % item for item in imports)


def _excludes_text() -> str:
    excludes = [
        "PIL",
        "Pillow",
        "numpy",
        "pandas",
        "matplotlib",
        "scipy",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "Crypto",
        "cryptography",
        "test",
        "unittest",
        "distutils",
        "setuptools",
        "pip",
        "wheel",
        "tensorflow",
        "torch",
        "opencv",
        "cv2",
    ]
    return "[\n%s\n    ]" % "".join("        %r,\n" % item for item in excludes)


def write_spec(spec_path: Path, console: bool, runtime_hook_path: Path) -> None:
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    name = "聊天室" if console else "聊天室无命令行"
    spec_path.write_text(
        f"""# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.building.datastruct import Tree

PROJECT_ROOT = Path({str(PROJECT_ROOT)!r})
STATIC_DIR = PROJECT_ROOT / 'static'
RUNTIME_HOOK = {str(runtime_hook_path)!r}

a = Analysis(
    [str(PROJECT_ROOT / 'main.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports={_hiddenimports_text()},
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[RUNTIME_HOOK],
    excludes={_excludes_text()},
    noarchive=False,
    optimize=2,
)

if STATIC_DIR.exists():
    a.datas += Tree(str(STATIC_DIR), prefix='static', excludes=[
        '.git',
        '.git/*',
        '.gitignore',
        '__pycache__',
        '*.pyc',
    ])

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name={name!r},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        'api-ms-win-*.dll',
        'vcruntime*.dll',
        'msvcp*.dll',
        'ucrtbase*.dll',
    ],
    runtime_tmpdir=None,
    console={console!r},
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
""",
        encoding="utf-8",
    )


def verify_static_inputs() -> None:
    mapping_file = STICKER_DIR / "mapping.json"
    if not mapping_file.exists():
        raise RuntimeError("Dynamic sticker mapping is missing: %s" % mapping_file)
    if not any(STICKER_DIR.glob("*.webp")):
        raise RuntimeError("Dynamic sticker .webp files are missing: %s" % STICKER_DIR)


def remove_old_outputs() -> None:
    for exe_path in (EXE_CONSOLE, EXE_NOCONSOLE):
        if exe_path.exists():
            print("Removing old output: %s" % exe_path)
            exe_path.unlink()


def verify_outputs() -> None:
    for exe_path in (EXE_CONSOLE, EXE_NOCONSOLE):
        if not exe_path.exists():
            raise RuntimeError("Build output missing: %s" % exe_path)
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print("Built: %s (%.1f MB)" % (exe_path, size_mb))


def build_all(args: argparse.Namespace) -> None:
    selection = select_python38()
    print("Python: %s via %s" % (selection.version, " ".join(selection.command)))
    check_pyinstaller(selection)
    verify_static_inputs()

    BUILD_HELPER_DIR.mkdir(parents=True, exist_ok=True)
    hook_path = BUILD_HELPER_DIR / "lanchat_passwords_runtime_hook.py"
    console_spec = BUILD_HELPER_DIR / "lanchat_console.spec"
    noconsole_spec = BUILD_HELPER_DIR / "lanchat_noconsole.spec"

    write_password_runtime_hook(
        hook_path,
        startup_password=args.startup_password,
        admin_password_1=args.admin_password_1,
        admin_password_2=args.admin_password_2,
    )
    write_spec(console_spec, console=True, runtime_hook_path=hook_path)
    write_spec(noconsole_spec, console=False, runtime_hook_path=hook_path)

    DIST_DIR.mkdir(exist_ok=True)
    remove_old_outputs()

    run_command(selection.command + ["-m", "PyInstaller", str(console_spec), "--noconfirm"])
    run_command(selection.command + ["-m", "PyInstaller", str(noconsole_spec), "--noconfirm"])
    verify_outputs()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build 聊天室.exe and 聊天室无命令行.exe with Python 3.8."
    )
    parser.add_argument(
        "--startup-password",
        default=os.environ.get("LANCHAT_STARTUP_PASSWORD", ""),
        help="Optional server startup password to embed at build time.",
    )
    parser.add_argument(
        "--admin-password-1",
        default=os.environ.get("LANCHAT_ADMIN_PASSWORD_1", ""),
        help="Optional account management admin password to embed at build time.",
    )
    parser.add_argument(
        "--admin-password-2",
        default=os.environ.get("LANCHAT_ADMIN_PASSWORD_2", ""),
        help="Optional admin log password to embed at build time.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        build_all(parse_args(argv))
        return 0
    except Exception as exc:
        print("[error] %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
