#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys


def _read_memory_text(argv: list[str]) -> str:
    if len(argv) > 1:
        return " ".join(part.strip() for part in argv[1:] if part.strip())
    if not sys.stdin.isatty():
        return " ".join(part.strip() for part in sys.stdin.read().splitlines() if part.strip())
    raise SystemExit("Usage: append_memory.py <memory text>")


def main() -> int:
    memory_text = _read_memory_text(sys.argv)
    if not memory_text:
        raise SystemExit("Memory text cannot be empty.")

    memory_root = Path(os.environ.get("AGENTS_MEMORY_DIR", Path(__file__).resolve().parent / "memories"))
    memory_root.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    memory_path = memory_root / f"{now:%Y-%m-%d}.md"
    entry = f"{now:%H:%M} > {memory_text}\n"

    prefix = ""
    if memory_path.exists() and memory_path.stat().st_size > 0:
        with memory_path.open("rb") as existing_file:
            existing_file.seek(-1, os.SEEK_END)
            if existing_file.read(1) != b"\n":
                prefix = "\n"

    with memory_path.open("a", encoding="utf-8") as memory_file:
        memory_file.write(prefix)
        memory_file.write(entry)

    print(memory_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
