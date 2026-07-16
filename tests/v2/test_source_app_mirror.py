from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src" / "lovv_agent_v2"
DEPLOY_ROOT = REPO_ROOT / "app" / "LovvAgentV2" / "lovv_agent_v2"


def test_deploy_package_matches_canonical_source() -> None:
    source_files = _package_files(SOURCE_ROOT)
    deploy_files = _package_files(DEPLOY_ROOT)

    assert source_files == deploy_files
    for relative_path in sorted(source_files):
        assert _normalized_text(SOURCE_ROOT / relative_path) == _normalized_text(
            DEPLOY_ROOT / relative_path,
        ), relative_path


def _package_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _normalized_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")
