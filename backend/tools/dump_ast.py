#!/usr/bin/env python
"""
Dump AST analysis results to JSON using the project's analyzer.

Usage:
  python backend/tools/dump_ast.py path/to/file.py
  python backend/tools/dump_ast.py path/to/file.py --pretty
"""

import argparse
import json
import sys
from pathlib import Path

from backend.api.diff_analyzer import PythonASTAnalyzer


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump AST analysis results as JSON.")
    parser.add_argument("file", help="Path to a Python source file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 2
    if file_path.suffix.lower() != ".py":
        print(f"Not a Python file: {file_path}", file=sys.stderr)
        return 2

    source = file_path.read_text(encoding="utf-8")
    analyzer = PythonASTAnalyzer(source, str(file_path))
    nodes = analyzer.extract_nodes()

    payload = {
        "file": str(file_path),
        "node_count": len(nodes),
        "nodes": [n.to_dict() for n in nodes],
    }

    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
