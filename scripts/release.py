#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LANChat Hub Release Pipeline Tool

Commands:
    python scripts/release.py bump patch          Bump patch version
    python scripts/release.py bump minor          Bump minor version
    python scripts/release.py bump major          Bump major version
    python scripts/release.py build               Build executables with PyInstaller
    python scripts/release.py release             Full release pipeline
    python scripts/release.py release --skip-build  Release without building
    python scripts/release.py show                Show current version info
    --dry-run can be added to any command for preview
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Project root: scripts/release.py -> scripts/ dir -> project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
MAIN_PY = os.path.join(BASE_DIR, "main.py")
README_MD = os.path.join(BASE_DIR, "README.md")
PACKAGE_JSON = os.path.join(BASE_DIR, "package.json")
SPEC_CONSOLE = os.path.join(BASE_DIR, "聊天室.spec")
SPEC_NOCONSOLE = os.path.join(BASE_DIR, "聊天室无命令行.spec")
DIST_DIR = os.path.join(BASE_DIR, "dist")
RELEASES_DIR = os.path.join(BASE_DIR, "releases")
LICENSE_FILE = os.path.join(BASE_DIR, "LICENSE")
CONFIG_EXAMPLE = os.path.join(BASE_DIR, "config.json.example")

EXE_CONSOLE = os.path.join(DIST_DIR, "聊天室.exe")
EXE_NOCONSOLE = os.path.join(DIST_DIR, "聊天室无命令行.exe")

# Global dry-run flag
DRY_RUN = False


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def read_version() -> str:
    """Read current version from VERSION file.

    Returns:
        Version string e.g. "1.0.0"

    If the VERSION file does not exist, creates it with default "1.0.0".
    """
    if not os.path.exists(VERSION_FILE):
        print(f"[warn] VERSION file not found, creating with default '1.0.0'")
        _write_file(VERSION_FILE, "1.0.0\n")
        return "1.0.0"
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def parse_version(version_str: str) -> tuple:
    """Parse a version string into (major, minor, patch) tuple."""
    parts = version_str.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: '{version_str}'. Expected X.Y.Z")
    return int(parts[0]), int(parts[1]), int(parts[2])


def bump_version(current: str, component: str) -> str:
    """Bump a version component.

    Args:
        current: Current version string e.g. "1.0.0"
        component: One of "major", "minor", "patch"

    Returns:
        New version string e.g. "1.0.1"
    """
    major, minor, patch = parse_version(current)
    if component == "major":
        major += 1
        minor = 0
        patch = 0
    elif component == "minor":
        minor += 1
        patch = 0
    elif component == "patch":
        patch += 1
    else:
        raise ValueError(f"Unknown component: '{component}'. Use major/minor/patch")
    return f"{major}.{minor}.{patch}"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _read_text(path: str) -> str:
    """Read entire text file, returning content or empty string."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _write_file(path: str, content: str) -> None:
    """Write content to file, respecting dry-run mode."""
    if DRY_RUN:
        print(f"  [dry-run] Would write: {path}")
        return
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def _run(cmd: list, cwd: str = None, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a subprocess command.

    Args:
        cmd: Command as list of strings.
        cwd: Working directory for command.
        check: If True, exit on non-zero return code.
        capture: If True, capture stdout/stderr.

    Returns:
        CompletedProcess instance.
    """
    if DRY_RUN:
        print(f"  [dry-run] Would run: {' '.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or BASE_DIR,
            check=False,
            capture_output=capture,
            text=True,
        )
        if check and result.returncode != 0:
            print(f"[error] Command failed (exit {result.returncode}): {' '.join(cmd)}")
            if capture:
                print(f"  stderr: {result.stderr.strip()}")
            sys.exit(1)
        return result
    except FileNotFoundError:
        print(f"[error] Command not found: {cmd[0]}")
        if check:
            sys.exit(1)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=f"Not found: {cmd[0]}")


# ---------------------------------------------------------------------------
# Pre-build checks
# ---------------------------------------------------------------------------

def _check_debug_mode() -> None:
    """Check if debug mode is enabled in the Flask app.

    Reads main.py and verifies that `app.run(debug=True)` is NOT present.
    If debug mode is ON, prints a warning and exits with code 1.
    """
    main_content = _read_text(MAIN_PY)

    if DRY_RUN:
        print("  [dry-run] Would check debug mode in main.py")
        return

    # Check app.run(debug=True) or debug=True in app.run
    if re.search(r'app\.run\(.*debug\s*=\s*True', main_content):
        print("[error] Debug mode is ON in main.py!")
        print("  Found: app.run(debug=True)")
        print("  Please set debug=False before building a release.")
        sys.exit(1)

    # Also check if FLASK_DEBUG env var is set (less reliable but worth checking)
    if re.search(r'FLASK_DEBUG|flask_debug', main_content):
        print("[warn] Found FLASK_DEBUG reference in main.py")
        print("  Verify debug mode is not accidentally enabled at runtime.")

    print("  [ok] Debug mode check passed (app.run(debug=False))")


def _check_python_version() -> None:
    """Check Python version and warn if not using Python 3.8.

    For Windows 7 compatibility, Python 3.8 is recommended.
    """
    current = sys.version_info
    expected = (3, 8)

    if DRY_RUN:
        print(f"  [dry-run] Would check Python version (current: {sys.version.split()[0]})")
        return

    if current.major == 3 and current.minor == 8:
        print(f"  [ok] Python version: {sys.version.split()[0]} (Win7 compatible)")
    elif current.major == 3 and current.minor < 8:
        print(f"[warn] Python {current.major}.{current.minor} is too old!")
        print("  Python 3.8+ is required for this project.")
    else:
        print(f"[warn] Python {current.major}.{current.minor} detected")
        print("  Python 3.8 is recommended for Windows 7 compatibility.")
        print(f"  Current: {sys.version.split()[0]}")
        print(f"  If Win7 support is needed, rebuild with Python 3.8.")


# ---------------------------------------------------------------------------
# Version display
# ---------------------------------------------------------------------------

def show_version() -> None:
    """Display current version and all locations where it is referenced."""
    version = read_version()

    # ANSI color helpers
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    def _ctag(tag: str) -> str:
        """Return colored tag for output."""
        return tag

    print(f"\n{BOLD}LANChat Hub - Version Info{RESET}\n")
    print(f"  Current version: {GREEN}v{version}{RESET}")

    # Check VERSION file
    print(f"\n  {CYAN}[VERSION file]{RESET}")
    print(f"    Path: {VERSION_FILE}")
    print(f"    Content: {YELLOW}{version}{RESET}")

    # Check main.py
    print(f"\n  {CYAN}[main.py]{RESET}")
    main_content = _read_text(MAIN_PY)
    match = re.search(r'v(\d+\.\d+\.\d+)', main_content)
    if match:
        print(f"    Line 3: {YELLOW}LANChat Hub v{match.group(1)}{RESET}")
    else:
        print(f"    {YELLOW}(version not found in docstring){RESET}")

    # Check README.md
    print(f"\n  {CYAN}[README.md]{RESET}")
    readme = _read_text(README_MD)
    badge_match = re.search(r'version-(\d+\.\d+\.\d+)-blue', readme)
    zip_match = re.search(r'v(\d+\.\d+\.\d+)-Windows\.zip', readme)
    if badge_match:
        print(f"    Badge: {YELLOW}version-{badge_match.group(1)}-blue{RESET}")
    if zip_match:
        print(f"    Zip ref: {YELLOW}LANChat-Hub-v{zip_match.group(1)}-Windows.zip{RESET}")

    # Check package.json
    print(f"\n  {CYAN}[package.json]{RESET}")
    pkg = _read_text(PACKAGE_JSON)
    pkg_match = re.search(r'"version":\s*"(\d+\.\d+\.\d+)"', pkg)
    if pkg_match:
        print(f"    version field: {YELLOW}{pkg_match.group(1)}{RESET}")
    else:
        print(f"    {YELLOW}(version field not found){RESET}")

    print()


# ---------------------------------------------------------------------------
# Source file version update
# ---------------------------------------------------------------------------

def _update_main_py(old_ver: str, new_ver: str) -> None:
    """Update version in main.py docstring (line 3)."""
    if not os.path.exists(MAIN_PY):
        print(f"  [warn] main.py not found, skipping")
        return

    content = _read_text(MAIN_PY)
    # Line 3: "LANChat Hub v1.0.0 - 局域网聊天应用"
    pattern = re.compile(r'(LANChat Hub )v' + re.escape(old_ver) + r'( - 局域网聊天应用)')
    new_content, count = pattern.subn(r'\g<1>v' + new_ver + r'\g<2>', content)
    if count == 0:
        print(f"  [warn] Version pattern not found in main.py")
        return

    if DRY_RUN:
        print(f"  [dry-run] main.py: v{old_ver} -> v{new_ver} (1 occurrence)")
    else:
        _write_file(MAIN_PY, new_content)
        print(f"  Updated main.py: v{old_ver} -> v{new_ver}")


def _update_readme(old_ver: str, new_ver: str) -> None:
    """Update version references in README.md."""
    if not os.path.exists(README_MD):
        print(f"  [warn] README.md not found, skipping")
        return

    content = _read_text(README_MD)
    old_escaped = re.escape(old_ver)
    changes = []

    # Update badge: version-1.0.0-blue -> version-{new}-blue
    # Use \g<1> to avoid ambiguity with version digits (e.g. "1.0.1" + \2 = \21)
    badge_pattern = re.compile(r'(version-)' + old_escaped + r'(-blue)')
    new_content, count1 = badge_pattern.subn(r'\g<1>' + new_ver + r'\g<2>', content)
    if count1 > 0:
        changes.append(f"badge: {old_ver} -> {new_ver}")
        content = new_content

    # Update zip filename: LANChat-Hub-v1.0.0-Windows.zip -> LANChat-Hub-v{new}-Windows.zip
    zip_pattern = re.compile(r'(LANChat-Hub-v)' + old_escaped + r'(-Windows\.zip)')
    new_content2, count2 = zip_pattern.subn(r'\g<1>' + new_ver + r'\g<2>', content)
    if count2 > 0:
        changes.append(f"zip ref: v{old_ver} -> v{new_ver}")
        content = new_content2

    # Also handle lowercase lanchat-hub-v1.0.0-Windows.zip
    lc_zip_pattern = re.compile(r'(lanchat-hub-v)' + old_escaped + r'(-Windows\.zip)')
    new_content3, count3 = lc_zip_pattern.subn(r'\g<1>' + new_ver + r'\g<2>', content)
    if count3 > 0:
        changes.append(f"lowercase zip ref: v{old_ver} -> v{new_ver}")
        content = new_content3

    if not changes:
        print(f"  [warn] No version references found in README.md")
        return

    if DRY_RUN:
        print(f"  [dry-run] README.md: {'; '.join(changes)}")
    else:
        _write_file(README_MD, content)
        print(f"  Updated README.md: {'; '.join(changes)}")


def _update_package_json(old_ver: str, new_ver: str) -> None:
    """Update version field in package.json."""
    if not os.path.exists(PACKAGE_JSON):
        print(f"  [warn] package.json not found, skipping")
        return

    content = _read_text(PACKAGE_JSON)
    old_escaped = re.escape(old_ver)
    pattern = re.compile(r'("version":\s*")' + old_escaped + r'(")')
    new_content, count = pattern.subn(r'\g<1>' + new_ver + r'\g<2>', content)

    if count == 0:
        print(f"  [warn] version field not found in package.json")
        return

    if DRY_RUN:
        print(f"  [dry-run] package.json: {old_ver} -> {new_ver}")
    else:
        _write_file(PACKAGE_JSON, new_content)
        print(f"  Updated package.json: {old_ver} -> {new_ver}")


def update_source_version(old_ver: str, new_ver: str) -> None:
    """Update all version references across project source files."""
    print(f"\nUpdating source files (v{old_ver} -> v{new_ver}):")
    _update_main_py(old_ver, new_ver)
    _update_readme(old_ver, new_ver)
    _update_package_json(old_ver, new_ver)


# ---------------------------------------------------------------------------
# Bump subcommand
# ---------------------------------------------------------------------------

def cmd_bump(component: str) -> str:
    """Bump the version.

    Args:
        component: 'major', 'minor', or 'patch'

    Returns:
        New version string.
    """
    old_ver = read_version()
    new_ver = bump_version(old_ver, component)

    print(f"\nBumping version: v{old_ver} -> v{new_ver} ({component})")

    if DRY_RUN:
        print(f"  [dry-run] Would write VERSION: {new_ver}")
    else:
        _write_file(VERSION_FILE, new_ver + "\n")
        print(f"  Wrote VERSION: {new_ver}")

    update_source_version(old_ver, new_ver)

    if DRY_RUN:
        print(f"\n[Dry-run complete] Would bump v{old_ver} -> v{new_ver}")
    else:
        print(f"\nVersion bumped: v{old_ver} -> v{new_ver}")

    return new_ver


# ---------------------------------------------------------------------------
# Build subcommand
# ---------------------------------------------------------------------------

def cmd_build() -> None:
    """Build executables with PyInstaller.

    Runs two builds:
    1. 聊天室.spec (console=True) -> dist/聊天室.exe
    2. 聊天室无命令行.spec (console=False) -> dist/聊天室无命令行.exe
    """
    version = read_version()
    print(f"\nBuilding LANChat Hub v{version} executables...")

    # Pre-build checks
    _check_debug_mode()
    _check_python_version()

    # Check spec files exist
    for spec, label in [(SPEC_CONSOLE, "console"), (SPEC_NOCONSOLE, "no-console")]:
        if not os.path.exists(spec):
            print(f"[error] Spec file not found: {spec}")
            sys.exit(1)

    # Clean previous build artifacts (but keep dist/)
    build_dir = os.path.join(BASE_DIR, "build")
    if not DRY_RUN:
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir, ignore_errors=True)
        # Clean old exe files
        for exe in [EXE_CONSOLE, EXE_NOCONSOLE]:
            if os.path.exists(exe):
                os.remove(exe)
    else:
        print(f"  [dry-run] Would clean build/ and old dist/*.exe")

    # Build with console
    print(f"\n  [1/2] Building with console: {os.path.basename(SPEC_CONSOLE)}")
    _run(["pyinstaller", "聊天室.spec", "--clean", "--noconfirm"])

    # Build without console
    print(f"  [2/2] Building without console: {os.path.basename(SPEC_NOCONSOLE)}")
    _run(["pyinstaller", "聊天室无命令行.spec", "--clean", "--noconfirm"])

    # Verify outputs
    if not DRY_RUN:
        for exe_path, label in [(EXE_CONSOLE, "console"), (EXE_NOCONSOLE, "no-console")]:
            if not os.path.exists(exe_path):
                print(f"[error] Build failed: {label} exe not found at {exe_path}")
                sys.exit(1)
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"    {label}: {os.path.basename(exe_path)} ({size_mb:.1f} MB)")
    else:
        print(f"  [dry-run] Would verify {EXE_CONSOLE}")
        print(f"  [dry-run] Would verify {EXE_NOCONSOLE}")

    print(f"\nBuild complete. Outputs in {DIST_DIR}/")
    print("  Note: static/telegram_stickers/ is excluded from the build")
    print("  (configured in the .spec file via Tree(excludes=['telegram_stickers']))")


# ---------------------------------------------------------------------------
# Release zip
# ---------------------------------------------------------------------------

def create_release_zip(version: str) -> str:
    """Create release zip archive.

    Args:
        version: Version string e.g. "1.0.0"

    Returns:
        Path to created zip file.
    """
    zip_name = f"LANChat-Hub-v{version}-Windows.zip"
    zip_path = os.path.join(RELEASES_DIR, zip_name)

    print(f"\nCreating release archive: {zip_name}")

    # Files to include in zip
    files_to_zip = [
        (EXE_CONSOLE, "聊天室.exe"),
        (EXE_NOCONSOLE, "聊天室无命令行.exe"),
        (README_MD, "README.md"),
        (LICENSE_FILE, "LICENSE"),
        (CONFIG_EXAMPLE, "config.json.example"),
    ]

    # Check source files existence
    for src, arcname in files_to_zip:
        if not os.path.exists(src):
            if src == LICENSE_FILE:
                print(f"  [warn] LICENSE file not found, skipping")
            elif src == CONFIG_EXAMPLE:
                print(f"  [warn] config.json.example not found, skipping")
            else:
                print(f"[error] Required file not found: {src}")
                sys.exit(1)

    if DRY_RUN:
        print(f"  [dry-run] Would create: {zip_path}")
        for src, arcname in files_to_zip:
            if os.path.exists(src):
                print(f"    Add: {arcname}")
        return zip_path

    # Create releases directory
    os.makedirs(RELEASES_DIR, exist_ok=True)

    # Create zip
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arcname in files_to_zip:
            if os.path.exists(src):
                zf.write(src, arcname)
                size_mb = os.path.getsize(src) / (1024 * 1024)
                print(f"  Added: {arcname} ({size_mb:.1f} MB)")

    zip_size = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"  Archive: {zip_name} ({zip_size:.1f} MB)")
    print(f"  Location: {zip_path}")

    return zip_path


# ---------------------------------------------------------------------------
# GitHub release
# ---------------------------------------------------------------------------

def _check_gh_cli() -> bool:
    """Check if gh CLI is available."""
    result = _run(["gh", "--version"], check=False, capture=True)
    return result.returncode == 0


def _get_release_notes(version: str) -> str:
    """Generate release notes from git log since last tag."""
    # Try to get commits since last tag
    try:
        last_tag_result = _run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture=True,
            check=False,
        )
        if last_tag_result.returncode == 0:
            last_tag = last_tag_result.stdout.strip()
            log_result = _run(
                ["git", "log", f"{last_tag}..HEAD", "--oneline", "--no-merges"],
                capture=True,
                check=False,
            )
        else:
            # No previous tags, use recent commits
            log_result = _run(
                ["git", "log", "-20", "--oneline", "--no-merges"],
                capture=True,
                check=False,
            )
    except Exception:
        log_result = subprocess.CompletedProcess([], 0, stdout="", stderr="")

    commits = log_result.stdout.strip().split("\n") if log_result.stdout.strip() else []
    if not commits:
        return f"LANChat Hub v{version} release"

    notes = f"## What's Changed in v{version}\n\n"
    for commit in commits[:30]:  # Limit to 30
        # Skip merge commits, remove hash prefix
        clean = re.sub(r'^[0-9a-f]+\s+', '', commit.strip())
        notes += f"- {clean}\n"

    return notes


def cmd_github_release(version: str, zip_path: str) -> None:
    """Create a GitHub release.

    Args:
        version: Version string e.g. "1.0.0"
        zip_path: Path to release zip file.
    """
    print(f"\nCreating GitHub release v{version}...")

    if not _check_gh_cli():
        print("  [warn] GitHub CLI (gh) not installed or not authenticated")
        print("  Skipping GitHub release. To create manually:")
        print(f"    git tag v{version}")
        print(f"    git push origin v{version}")
        print(f"    gh release create v{version} {zip_path}")
        return

    tag = f"v{version}"

    # Generate release notes
    notes = _get_release_notes(version)
    print(f"  Release notes:\n{notes}")

    if DRY_RUN:
        print(f"  [dry-run] Would run: git tag {tag}")
        print(f"  [dry-run] Would run: git push origin {tag}")
        print(f"  [dry-run] Would run: gh release create {tag} {zip_path}")
        return

    # Create and push tag
    print(f"  Creating tag: {tag}")
    _run(["git", "tag", tag])

    print(f"  Pushing tag: {tag}")
    _run(["git", "push", "origin", tag])

    # Create GitHub release
    print(f"  Creating GitHub release...")
    _run([
        "gh", "release", "create", tag,
        zip_path,
        "--title", tag,
        "--notes", notes,
    ])

    print(f"  GitHub release created: {tag}")


# ---------------------------------------------------------------------------
# Release subcommand (full pipeline)
# ---------------------------------------------------------------------------

def cmd_release(component: str = "patch", skip_build: bool = False) -> None:
    """Full release pipeline.

    Steps:
    1. Bump version
    2. Build executables (optional)
    3. Create release zip
    4. Create GitHub release

    Args:
        component: Version component to bump (major/minor/patch)
        skip_build: If True, skip building executables
    """
    print("\n" + "=" * 60)
    print("  LANChat Hub Release Pipeline")
    print("=" * 60)

    # Pre-build checks
    _check_debug_mode()
    _check_python_version()

    # Step 1: Bump version
    new_ver = cmd_bump(component)

    # Step 2: Build
    if not skip_build:
        cmd_build()
    else:
        print("\n  [skip] Build step skipped (--skip-build)")

    # Step 3: Create zip
    zip_path = create_release_zip(new_ver)

    # Step 4: GitHub release
    cmd_github_release(new_ver, zip_path)

    # Summary
    print("\n" + "=" * 60)
    print(f"  Release v{new_ver} complete!")
    print("=" * 60)
    print(f"  VERSION file:    {VERSION_FILE}")
    print(f"  Release archive: {zip_path}")
    if not DRY_RUN:
        print(f"  Git tag:         v{new_ver}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="LANChat Hub Release Pipeline Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/release.py --dry-run bump patch   # Preview a patch bump
  python scripts/release.py bump patch              # Bump patch version
  python scripts/release.py bump minor              # Bump minor version
  python scripts/release.py bump major              # Bump major version
  python scripts/release.py build                   # Build executables
  python scripts/release.py release                 # Full release pipeline
  python scripts/release.py release --skip-build    # Release without building
  python scripts/release.py show                    # Show version info
""",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without actually making them",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # bump
    bump_parser = subparsers.add_parser("bump", help="Bump version")
    bump_parser.add_argument(
        "component",
        choices=["major", "minor", "patch"],
        help="Version component to bump",
    )

    # build
    subparsers.add_parser("build", help="Build executables with PyInstaller")

    # release
    release_parser = subparsers.add_parser("release", help="Full release pipeline")
    release_parser.add_argument(
        "component",
        nargs="?",
        default="patch",
        choices=["major", "minor", "patch"],
        help="Version component to bump (default: patch)",
    )
    release_parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip building executables, just bump + zip source",
    )

    # show
    subparsers.add_parser("show", help="Show current version info")

    return parser.parse_args()


def main() -> None:
    """Entry point."""
    global DRY_RUN

    args = parse_args()
    DRY_RUN = args.dry_run

    if not args.command:
        show_version()
        return

    if DRY_RUN:
        print("\n" + "=" * 60)
        print("  DRY-RUN MODE - No changes will be made")
        print("=" * 60)

    if args.command == "bump":
        cmd_bump(args.component)

    elif args.command == "build":
        cmd_build()

    elif args.command == "release":
        cmd_release(component=args.component, skip_build=args.skip_build)

    elif args.command == "show":
        show_version()

    if DRY_RUN:
        print("\n" + "=" * 60)
        print("  DRY-RUN COMPLETE - No changes were made")
        print("=" * 60)
        print("  Remove --dry-run to apply changes.\n")


if __name__ == "__main__":
    main()
