from agentic_os import __version__


def test_package_exposes_version() -> None:
    assert __version__ == "1.0.1"


def test_release_version_files_in_sync() -> None:
    """All version declarations must match — Cargo.lock included.

    The v1.0.1 tag shipped with Cargo.lock still at 1.0.0 because cargo
    only regenerates the lock at build time; this guard turns that
    drift into a CI failure.
    """
    import json
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    versions = {"pyproject.toml": pyproject["project"]["version"]}
    versions["__init__.py"] = __version__

    desktop = root / "apps/desktop"
    versions["package.json"] = json.loads(
        (desktop / "package.json").read_text(encoding="utf-8")
    )["version"]
    versions["tauri.conf.json"] = json.loads(
        (desktop / "src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )["version"]
    cargo_toml = tomllib.loads(
        (desktop / "src-tauri/Cargo.toml").read_text(encoding="utf-8")
    )
    versions["Cargo.toml"] = cargo_toml["package"]["version"]
    cargo_lock = tomllib.loads(
        (desktop / "src-tauri/Cargo.lock").read_text(encoding="utf-8")
    )
    app_name = cargo_toml["package"]["name"]
    versions["Cargo.lock"] = next(
        p["version"] for p in cargo_lock["package"] if p["name"] == app_name
    )

    assert len(set(versions.values())) == 1, f"version drift: {versions}"
