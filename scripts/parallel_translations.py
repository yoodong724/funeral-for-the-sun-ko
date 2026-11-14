#!/usr/bin/env python3
"""Check assigned translation files and merge them without calling a model."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Reuse the bundled, unchanged toolbox, regardless of the caller's directory.
# Do not create bytecode files inside that original distribution.
sys.dont_write_bytecode = True
FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK_ROOT / "toolbox" / "tools"))

from l10n_primitives.contracts import (  # noqa: E402
    TRANSLATION_FORMAT, load_canonical, load_catalog, load_translations, sha_string,
)
from l10n_primitives.core import (  # noqa: E402
    ToolError, ensure_new, fields, load_json, nonempty, pretty, require,
    revision, safe_absolute, safe_relative, write_new_files,
)
from l10n_primitives.operations import check_translation  # noqa: E402

VERSION = "0.2.0"
PLAN_FORMAT = "korean-localization-framework/translation-plan-v1"
REPORT_FORMAT = "korean-localization-framework/parallel-check-report-v1"
NOT_CHECKED = [
    "semantic_accuracy", "speaker_voice", "font_rendering", "pixel_width",
    "game_execution", "review_independence", "qa_approval",
    "source_files_current_on_disk", "installation_or_release_readiness",
]
NOTICE = (
    "배정 범위·기준 버전·지원되는 기술 규칙의 검사 결과입니다. "
    "모델 호출, 작업 스케줄링, 언어 검수, QA 승인, 설치·배포 게이트가 아닙니다."
)


@dataclass
class Inputs:
    catalog_path: Path
    canonical_path: Path
    plan_path: Path
    catalog: dict[str, Any]
    canonical: dict[str, Any]
    canonical_revision: str
    ignored_canonical: list[dict[str, Any]]
    plan: dict[str, Any]
    task_paths: dict[str, Path]


def path_key(path: Path) -> tuple[str, ...]:
    """Compare native path components with the same case folding on every OS."""
    return tuple(part.casefold() for part in path.parts)


def path_keys_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """A file path cannot also be another file's parent; siblings are allowed."""
    return left[:len(right)] == right or right[:len(left)] == left


def load_inputs(catalog_path: Path, canonical_path: Path, plan_path: Path) -> Inputs:
    catalog_path, canonical_path, plan_path = map(
        safe_absolute, (catalog_path, canonical_path, plan_path)
    )
    catalog = load_catalog(catalog_path)
    canonical, canonical_revision, ignored = load_canonical(canonical_path)
    require(canonical_revision is not None, "UNBOUND_CANONICAL", "canonical이 필요합니다.")
    plan = load_json(plan_path)
    fields(plan, {"format", "source_revision", "tasks"}, {"canonical_revision"})
    require(plan["format"] == PLAN_FORMAT, "UNSUPPORTED_FORMAT", "지원하지 않는 plan 형식입니다.")
    sha_string(plan["source_revision"])
    require(plan["source_revision"] == catalog["source_revision"], "STALE_CATALOG",
            "plan의 source_revision이 현재 catalog와 다릅니다.")
    require(plan.get("canonical_revision") is not None, "UNBOUND_CANONICAL",
            "plan에 전체 canonical 스냅샷의 canonical_revision이 필요합니다.")
    sha_string(plan["canonical_revision"])
    require(plan["canonical_revision"] == canonical_revision, "STALE_CANONICAL",
            "plan의 canonical_revision이 현재 전체 canonical과 다릅니다.")
    require(isinstance(plan["tasks"], list) and bool(plan["tasks"]), "SCHEMA_ERROR",
            "plan.tasks는 비어 있지 않은 목록이어야 합니다.")

    known = {u["id"] for u in catalog["units"]}
    owners: dict[str, str] = {}
    task_paths: dict[str, Path] = {}
    output_owners: dict[tuple[str, ...], str] = {}
    for task in plan["tasks"]:
        fields(task, {"task_id", "unit_ids", "translations"})
        task_id = nonempty(task["task_id"], "task_id")
        require(task_id not in task_paths, "DUPLICATE_TASK_ID", task_id)
        require(isinstance(task["unit_ids"], list) and bool(task["unit_ids"]),
                "SCHEMA_ERROR", f"{task_id}.unit_ids는 비어 있지 않은 목록이어야 합니다.")
        for uid in task["unit_ids"]:
            require(isinstance(uid, str) and uid in known, "UNKNOWN_UNIT",
                    f"{task_id}: catalog에 없는 배정 ID입니다.", {"unit_id": uid})
            require(uid not in owners, "OVERLAPPING_ASSIGNMENT",
                    "ID는 한 작업에 한 번만 배정할 수 있습니다.",
                    {"unit_id": uid, "task_ids": [owners.get(uid), task_id]})
            owners[uid] = task_id
        path = safe_relative(plan_path.parent, task["translations"])
        key = path_key(path)
        require(key not in output_owners, "DUPLICATE_TASK_OUTPUT",
                "서로 다른 작업이 같은 번역 파일을 사용할 수 없습니다.",
                {"task_ids": [output_owners.get(key), task_id]})
        for existing_key, owner in output_owners.items():
            require(not path_keys_overlap(key, existing_key), "TASK_OUTPUT_COLLISION",
                    "작업 결과 파일 경로끼리 부모·자식 관계가 될 수 없습니다.",
                    {"task_ids": [owner, task_id]})
        output_owners[key] = task_id
        task_paths[task_id] = path
    require(set(owners) == known, "PLAN_COVERAGE_MISMATCH",
            "plan은 catalog 전체 ID를 빠짐없이 배정해야 합니다.",
            {"missing_ids": [u["id"] for u in catalog["units"] if u["id"] not in owners]})
    return Inputs(catalog_path, canonical_path, plan_path, catalog, canonical,
                  canonical_revision, ignored, plan, task_paths)


def prepare_outputs(inputs: Inputs, out: Path | None, report: Path | None) -> tuple[Path | None, Path | None]:
    outputs = [safe_absolute(p) for p in (out, report) if p is not None]
    if len(outputs) == 2:
        a, b = outputs
        require(not path_keys_overlap(path_key(a), path_key(b)),
                "OUTPUT_COLLISION", "--out과 --report는 서로 독립된 새 파일 경로여야 합니다.")
    protected = [inputs.catalog_path, inputs.plan_path, *inputs.task_paths.values()]
    if not inputs.canonical_path.is_dir():
        protected.append(inputs.canonical_path)
    protected_keys = {path_key(p) for p in protected}
    for path in outputs:
        key = path_key(path)
        require(not any(path_keys_overlap(key, protected_key) for protected_key in protected_keys),
                "OUTPUT_IS_INPUT",
                "출력은 입력·배정된 작업 결과 파일과 동일하거나 부모·자식 경로가 될 수 없습니다.")
        if inputs.canonical_path.is_dir():
            canonical_key = path_key(inputs.canonical_path)
            require(key[:len(canonical_key)] != canonical_key, "OUTPUT_IN_SOURCE",
                    "canonical 디렉터리 안에는 출력하지 않습니다.")
        ensure_new(path, forbidden_files=tuple(protected),
                   forbidden_roots=(inputs.canonical_path,) if inputs.canonical_path.is_dir() else ())
    return (safe_absolute(out) if out is not None else None,
            safe_absolute(report) if report is not None else None)


def technical_summary(result: dict[str, Any]) -> dict[str, Any]:
    # The task's exact coverage is checked separately. Do not repeat the IDs of
    # every other task in each worker report as upstream's partial check does.
    return {key: result[key] for key in (
        "checks_version", "passed", "errors", "warnings", "translations_revision",
        "source_revision", "canonical_revision", "excluded_canonical_records", "not_checked",
    )} | {"checked_units": result["coverage"]["checked_units"]}


def inspect_task(inputs: Inputs, task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, int]:
    task_id = task["task_id"]
    result: dict[str, Any] = {
        "task_id": task_id,
        "translations": task["translations"],
        "assigned_ids": task["unit_ids"],
        "passed": False,
    }
    try:
        translations = load_translations(inputs.task_paths[task_id], inputs.catalog, allow_pending=True)
        require(translations.get("canonical_revision") is not None, "UNBOUND_CANONICAL",
                f"{task_id}: 번역에 전체 canonical_revision이 필요합니다.")
        require(translations["canonical_revision"] == inputs.canonical_revision, "STALE_CANONICAL",
                f"{task_id}: 번역이 plan 및 현재 canonical과 다른 기준에 연결되어 있습니다.")
        assigned = set(task["unit_ids"])
        supplied = {row["id"] for row in translations["translations"]}
        require(supplied == assigned, "TASK_COVERAGE_MISMATCH",
                f"{task_id}: 제출 ID가 배정 ID와 정확히 일치해야 합니다.",
                {"missing_assigned_ids": sorted(assigned - supplied),
                 "unassigned_ids": sorted(supplied - assigned)})
        check = check_translation(inputs.catalog, translations, inputs.canonical,
                                  inputs.canonical_revision, inputs.ignored_canonical, complete=False)
        result.update({"provided_rows": len(supplied), "exact_assignment_coverage": True,
                       "passed": check["passed"], "technical_check": technical_summary(check)})
        return result, translations, 0 if check["passed"] else 1
    except ToolError as exc:
        result["input_error"] = exc.payload()
        return result, None, 2


def merged_translations(inputs: Inputs, task_values: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["id"]: row for value in task_values for row in value["translations"]}
    provenance = []
    for task, value in zip(inputs.plan["tasks"], task_values):
        entry = {"task_id": task["task_id"], "translations": task["translations"],
                 "translations_revision": revision(value), "provenance": value.get("provenance", {})}
        if "notes" in value:
            entry["notes"] = value["notes"]
        provenance.append(entry)
    return {
        "format": TRANSLATION_FORMAT,
        "source_revision": inputs.catalog["source_revision"],
        "canonical_revision": inputs.canonical_revision,
        "provenance": {"kind": "deterministic_task_merge", "tool": "parallel_translations.py",
                       "tool_version": VERSION, "plan_revision": revision(inputs.plan), "tasks": provenance},
        "translations": [by_id[u["id"]] for u in inputs.catalog["units"]],
    }


def run(args: argparse.Namespace) -> tuple[bytes, int]:
    inputs = load_inputs(args.catalog, args.canonical, args.plan)
    selected = inputs.plan["tasks"]
    if args.command == "check-task":
        selected = [task for task in selected if task["task_id"] == args.task_id]
        require(bool(selected), "UNKNOWN_TASK", args.task_id)
    out, report_path = prepare_outputs(inputs, getattr(args, "out", None), args.report)

    task_reports = []
    task_values = []
    exit_code = 0
    for task in selected:
        result, value, code = inspect_task(inputs, task)
        task_reports.append(result)
        if value is not None:
            task_values.append(value)
        exit_code = max(exit_code, code)

    report: dict[str, Any] = {
        "format": REPORT_FORMAT, "tool": "parallel_translations", "tool_version": VERSION,
        "command": args.command, "source_revision": inputs.catalog["source_revision"],
        "canonical_revision": inputs.canonical_revision, "plan_revision": revision(inputs.plan),
        "scope": {"catalog_units": len(inputs.catalog["units"]),
                  "plan_tasks": len(inputs.plan["tasks"]),
                  "checked_task_ids": [task["task_id"] for task in selected],
                  "assigned_units": sum(len(task["unit_ids"]) for task in selected),
                  "complete_catalog_required": args.command == "merge"},
        "tasks": task_reports, "not_checked": NOT_CHECKED.copy(), "notice": NOTICE,
        "originals_written": False, "merged_output_written": False,
    }
    merged = None
    if args.command == "check-task":
        report["not_checked"].append("unselected_task_outputs")
    elif exit_code == 0:
        merged = merged_translations(inputs, task_values)
        aggregate = check_translation(inputs.catalog, merged, inputs.canonical,
                                      inputs.canonical_revision, inputs.ignored_canonical, complete=True)
        report["aggregate_check"] = aggregate
        if not aggregate["passed"]:
            exit_code = 1
            merged = None
        else:
            report["merged_output"] = str(out)
            report["merged_translations_revision"] = revision(merged)
            report["merged_output_written"] = True
    report.update({"ok": exit_code == 0, "passed": exit_code == 0, "exit_code": exit_code})

    # Serialize all outputs before creating any of them. The reused exclusive
    # writer removes files created by this call on a handled write failure.
    report_raw = pretty(report)
    outputs = {}
    if merged is not None:
        require(out is not None, "SCHEMA_ERROR", "merge에는 --out이 필요합니다.")
        outputs[out] = pretty(merged)
    if report_path is not None:
        outputs[report_path] = report_raw
    if outputs:
        write_new_files(outputs)
    return report_raw, exit_code


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="배정된 번역의 결정적 기술 검사와 새 파일 병합. 모델·언어 검수·QA 호출 없음.")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("check-task", "merge"):
        item = sub.add_parser(command)
        item.add_argument("--catalog", type=Path, required=True)
        item.add_argument("--canonical", type=Path, required=True)
        item.add_argument("--plan", type=Path, required=True)
        item.add_argument("--report", type=Path)
        if command == "check-task":
            item.add_argument("--task-id", required=True)
        else:
            item.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        output, exit_code = run(args)
        sys.stdout.write(output.decode("utf-8"))
        return exit_code
    except ToolError as exc:
        result = exc.payload()
    except OSError as exc:
        result = {"ok": False, "error": "IO_ERROR", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
