from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.todo_import import import_legacy_todo


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a legacy todo-reminder JSON export")
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_legacy_todo(args.json_path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
