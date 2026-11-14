#!/usr/bin/env python3
"""Minimal localization CLI. Python 3.11+, standard library only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from l10n_primitives import __version__
from l10n_primitives import operations as ops
from l10n_primitives.core import ToolError


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="독립 한글화 도구 5개. 작업 순서·모델·승인 상태는 관리하지 않습니다.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("extract", help="UTF-8 JSON 객체 문자열을 명시한 범위에서 추출")
    e.add_argument("--root", required=True, type=Path)
    e.add_argument("--config", required=True, type=Path)
    e.add_argument("--out", required=True, type=Path)
    e.add_argument("--template-out", type=Path)
    c = sub.add_parser("check", help="번역의 기술적 제약 검사; 상태 변경 없음")
    c.add_argument("--catalog", required=True, type=Path)
    c.add_argument("--translations", required=True, type=Path)
    c.add_argument("--canonical", type=Path)
    c.add_argument("--complete", action="store_true", help="catalog 전체 ID 제출 여부도 검사")
    c.add_argument("--out", type=Path)
    i = sub.add_parser("inject", help="원본 해시 확인 후 새 리소스 디렉터리에 재삽입; 검수 게이트 없음")
    i.add_argument("--root", required=True, type=Path)
    i.add_argument("--catalog", required=True, type=Path)
    i.add_argument("--translations", required=True, type=Path)
    i.add_argument("--out-dir", required=True, type=Path)
    l = sub.add_parser("lookup", help="canonical에서 부분문자열 검색")
    l.add_argument("--canonical", required=True, type=Path)
    l.add_argument("--query", required=True)
    l.add_argument("--section", default="all", choices=["all", "glossary", "characters", "scenes", "decisions", "style"])
    l.add_argument("--status", default="all", choices=["all", "approved", "proposed", "unknown", "rejected", "deprecated"])
    l.add_argument("--limit", default=20, type=int)
    d = sub.add_parser("diff", help="두 catalog의 원문·문맥·제약 변경 비교")
    d.add_argument("--old", required=True, type=Path)
    d.add_argument("--new", required=True, type=Path)
    d.add_argument("--out", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        if a.command == "extract":
            result = ops.extract(a.root, a.config, a.out, a.template_out)
        elif a.command == "check":
            result = ops.check(a.catalog, a.translations, a.canonical, a.out, complete=a.complete)
        elif a.command == "inject":
            result = ops.inject(a.root, a.catalog, a.translations, a.out_dir)
        elif a.command == "lookup":
            result = ops.lookup(a.canonical, a.query, a.section, a.status, a.limit)
        else:
            result = ops.diff(a.old, a.new, a.out)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if result.get("ok", True) else 1
    except ToolError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False, indent=2))
        return 2
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "IO_ERROR", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
