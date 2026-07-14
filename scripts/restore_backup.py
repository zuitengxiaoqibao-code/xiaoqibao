import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from qibao_api.gongbu.backup_service import BackupService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a Qibao backup and restore it to a new runtime directory."
    )
    parser.add_argument("backup_id")
    parser.add_argument("target", type=Path)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".runtime")
    arguments = parser.parse_args()
    service = BackupService(arguments.data_dir)
    restored = service.restore_to(arguments.backup_id, arguments.target)
    print(f"Restored verified backup to: {restored}")
    print("Start the API with QIBAO_DATA_DIR pointing to this directory for validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
