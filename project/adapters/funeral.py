"""Read and compare Funeral for the Sun's unencrypted Godot 4 PCK files.

The resource-byte check in this module does not validate the meaning of a
changed Godot resource, the game's name logic, or translation quality.  Those
checks require the game-specific mapping and are not implemented here yet.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct


class PckError(ValueError):
    """The pack or its contents do not match the supported contract."""


@dataclass(frozen=True)
class PckEntry:
    offset: int
    size: int
    md5: bytes
    flags: int
    index_offset: int
    name_bytes: bytes


@dataclass(frozen=True)
class PckIndex:
    engine: tuple[int, int, int]
    flags: int
    reserved: bytes
    entries: dict[str, PckEntry]
    base: int
    directory_end: int


def _read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise PckError("truncated PCK")
    return data


def _canonical_relative_path(value):
    return (isinstance(value, str) and bool(value) and "\\" not in value and ":" not in value
            and "\0" not in value and not value.startswith("/")
            and all(part not in ("", ".", "..") for part in value.split("/")))


def inspect_pck(path):
    """Read the index of an unencrypted standalone PCK v2."""
    path = Path(path)
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        header = _read_exact(stream, 100)
        if header[:4] != b"GDPC":
            raise PckError("not a standalone Godot PCK")
        version, major, minor, patch, flags, base = struct.unpack_from("<IIIIIQ", header, 4)
        if version != 2 or flags != 0:
            raise PckError("unsupported PCK version or pack flags")
        if base < 100 or base > file_size:
            raise PckError("invalid file base")
        count = struct.unpack_from("<I", header, 96)[0]
        entries = {}
        for _ in range(count):
            length = struct.unpack("<I", _read_exact(stream, 4))[0]
            if length == 0 or length > base - stream.tell():
                raise PckError("invalid entry name length")
            name_bytes = _read_exact(stream, length)
            raw_name = name_bytes.rstrip(b"\0")
            if not raw_name or b"\0" in raw_name:
                raise PckError("invalid entry name")
            try:
                name = raw_name.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PckError("entry name is not UTF-8") from exc
            if not _canonical_relative_path(name):
                raise PckError("noncanonical PCK entry path")
            index_offset = stream.tell()
            offset, size = struct.unpack("<QQ", _read_exact(stream, 16))
            digest = _read_exact(stream, 16)
            entry_flags = struct.unpack("<I", _read_exact(stream, 4))[0]
            if name in entries or entry_flags != 0:
                raise PckError("duplicate entry or unsupported entry flags")
            if offset > file_size - base or size > file_size - base - offset:
                raise PckError("entry outside PCK")
            entries[name] = PckEntry(base + offset, size, digest, entry_flags, index_offset, name_bytes)
        directory_end = stream.tell()
        if directory_end > base:
            raise PckError("PCK index overlaps file data")
        cursor = base
        for entry in sorted(entries.values(), key=lambda item: item.offset):
            if entry.offset < cursor:
                raise PckError("overlapping PCK entries are not supported")
            cursor = entry.offset + entry.size
    return PckIndex((major, minor, patch), flags, header[32:96], entries, base, directory_end)


def _entry_sha256(stream, entry):
    stream.seek(entry.offset)
    remaining = entry.size
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    while remaining:
        block = _read_exact(stream, min(remaining, 1024 * 1024))
        md5.update(block)
        sha256.update(block)
        remaining -= len(block)
    if md5.digest() != entry.md5:
        raise PckError("PCK entry checksum does not match its index")
    return sha256.hexdigest()


def _range_is_zero(stream, start, length):
    stream.seek(start)
    while length:
        block = _read_exact(stream, min(length, 1024 * 1024))
        if block.strip(b"\0"):
            return False
        length -= len(block)
    return True


def _same_range(left, left_start, right, right_start, length):
    left.seek(left_start)
    right.seek(right_start)
    while length:
        size = min(length, 1024 * 1024)
        if _read_exact(left, size) != _read_exact(right, size):
            return False
        length -= size
    return True


def _verify_pack_padding(source_file, result_file, source, result, source_size, result_size, order):
    if not _same_range(source_file, source.directory_end, result_file, result.directory_end,
                       source.base - source.directory_end):
        raise PckError("PCK directory padding changed")
    source_cursor = source.base
    result_cursor = result.base
    for name in order:
        source_entry = source.entries[name]
        result_entry = result.entries[name]
        source_gap = source_entry.offset - source_cursor
        result_gap = result_entry.offset - result_cursor
        if _range_is_zero(source_file, source_cursor, source_gap):
            if not _range_is_zero(result_file, result_cursor, result_gap):
                raise PckError("PCK padding changed")
        elif (result_gap < source_gap
              or not _same_range(source_file, source_cursor, result_file, result_cursor, source_gap)
              or not _range_is_zero(result_file, result_cursor + source_gap, result_gap - source_gap)):
            raise PckError("PCK data between entries changed")
        source_cursor = source_entry.offset + source_entry.size
        result_cursor = result_entry.offset + result_entry.size
    source_tail = source_size - source_cursor
    result_tail = result_size - result_cursor
    if source_tail != result_tail or not _same_range(source_file, source_cursor, result_file, result_cursor, source_tail):
        raise PckError("PCK trailing bytes changed")


def verify_resource_bytes(original, payload, expected_replacements, *, expected_original_sha256):
    """Verify all pack entries against original bytes or expected SHA-256s.

    ``expected_replacements`` maps existing entry paths to the SHA-256 of the
    prepared replacement resource. It does not describe or validate individual
    fields within those resources.
    """
    original = Path(original)
    payload = Path(payload)
    if not isinstance(expected_original_sha256, str) or len(expected_original_sha256) != 64:
        raise PckError("invalid source PCK hash")
    if any(char not in "0123456789abcdef" for char in expected_original_sha256):
        raise PckError("invalid source PCK hash")
    with original.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_original_sha256:
            raise PckError("source PCK does not match the expected revision")
    source = inspect_pck(original)
    result = inspect_pck(payload)
    if (source.engine, source.flags, source.reserved, source.base, source.directory_end) != (
            result.engine, result.flags, result.reserved, result.base, result.directory_end):
        raise PckError("PCK header metadata changed")
    if source.entries.keys() != result.entries.keys():
        raise PckError("PCK entry paths changed")
    if list(source.entries) != list(result.entries):
        raise PckError("PCK directory order changed")
    if any(source.entries[name].name_bytes != result.entries[name].name_bytes for name in source.entries):
        raise PckError("PCK directory name encoding changed")
    source_physical = sorted(source.entries, key=lambda name: source.entries[name].offset)
    result_physical = sorted(result.entries, key=lambda name: result.entries[name].offset)
    if source_physical != result_physical:
        raise PckError("PCK data order changed")
    if any(source.entries[name].offset % 16 != result.entries[name].offset % 16 for name in source.entries):
        raise PckError("PCK entry alignment changed")
    if not isinstance(expected_replacements, dict):
        raise PckError("expected replacements must be a path-to-hash mapping")
    if not expected_replacements.keys() <= source.entries.keys():
        raise PckError("replacement entry is not in the source PCK")
    for name, digest in expected_replacements.items():
        if not isinstance(name, str) or not isinstance(digest, str) or len(digest) != 64:
            raise PckError("invalid replacement hash")
        if any(char not in "0123456789abcdef" for char in digest):
            raise PckError("invalid replacement hash")

    changed = []
    with original.open("rb") as source_file, payload.open("rb") as result_file:
        _verify_pack_padding(source_file, result_file, source, result, original.stat().st_size,
                             payload.stat().st_size, source_physical)
        for name, source_entry in source.entries.items():
            original_hash = _entry_sha256(source_file, source_entry)
            payload_hash = _entry_sha256(result_file, result.entries[name])
            if payload_hash != expected_replacements.get(name, original_hash):
                raise PckError(f"unexpected content for entry: {name}")
            if payload_hash != original_hash:
                changed.append(name)
    return {
        "scope": "resource_bytes_only",
        "entry_count": len(source.entries),
        "changed_entries": sorted(changed),
        "protected_fields": "not_checked",
        "translation_quality": "not_checked",
    }


class InputError(ValueError):
    """A requested operation has invalid inputs."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_mapping(path):
    import json
    from pathlib import PurePosixPath

    with Path(path).open("r", encoding="utf-8") as stream:
        mapping = json.load(stream, object_pairs_hook=_unique_object)
    if not isinstance(mapping, dict) or set(mapping) != {"format", "source_sha256", "replacements"}:
        raise InputError("invalid resource map fields")
    if mapping["format"] != "funeral-resource-map-v1" or not isinstance(mapping["replacements"], list):
        raise InputError("unsupported resource map")
    source_hash = mapping["source_sha256"]
    if not isinstance(source_hash, str) or len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash):
        raise InputError("invalid source hash")
    seen = set()
    for item in mapping["replacements"]:
        if not isinstance(item, dict) or set(item) != {"entry", "source", "file", "sha256"}:
            raise InputError("invalid replacement fields")
        if item["source"] not in ("localized", "asset"):
            raise InputError("invalid replacement source")
        for field in ("entry", "file"):
            value = item[field]
            if not _canonical_relative_path(value) or PurePosixPath(value).is_absolute():
                raise InputError(f"invalid {field} path")
        if item["entry"] in seen:
            raise InputError("duplicate replacement entry")
        seen.add(item["entry"])
        digest = item["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise InputError("invalid replacement hash")
    return mapping


def _replacement_path(directory, relative):
    directory = Path(directory).resolve(strict=True)
    if not directory.is_dir():
        raise InputError("replacement directory is not a directory")
    candidate = (directory / relative).resolve(strict=True)
    if not candidate.is_relative_to(directory) or not candidate.is_file():
        raise InputError("replacement file is outside its directory or is not a file")
    return candidate


def _default_gdre(root):
    import json

    root = Path(root).resolve(strict=True)
    with (root / "project/toolchain.json").open("r", encoding="utf-8") as stream:
        toolchain = json.load(stream, object_pairs_hook=_unique_object)
    try:
        record = toolchain["gdre"]
        files = [{"path": record["path"], "sha256": record["executable_sha256"]}, *record["companions"]]
    except (KeyError, TypeError) as exc:
        raise InputError("invalid GDRE toolchain record") from exc
    if len(files) != 3:
        raise InputError("GDRE toolchain must list its two companion files")
    resolved = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise InputError("invalid GDRE toolchain file")
        if not isinstance(item["path"], str) or not isinstance(item["sha256"], str):
            raise InputError("invalid GDRE toolchain file")
        path = _replacement_path(root, item["path"])
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise InputError("GDRE toolchain file hash differs from the record")
        resolved.append(path)
    if {path.name for path in resolved[1:]} != {"gdre_tools.pck", "libGodotMonoDecompNativeAOT.so"}:
        raise InputError("GDRE companion files are missing")
    if any(path.parent != resolved[0].parent for path in resolved[1:]):
        raise InputError("GDRE companion files must be beside the executable")
    return resolved[0]


def _read_additions(path):
    """Read the existing ordered additions-list format used by the PCK builder."""
    import json
    import sys

    # The adapter is also invoked directly as a script, outside package mode.
    if not __package__:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from project.adapters.pck_additions import Addition

    with Path(path).open("r", encoding="utf-8") as stream:
        rows = json.load(stream, object_pairs_hook=_unique_object)
    if not isinstance(rows, list) or not rows:
        raise InputError("additions must be a nonempty ordered list")
    result = []
    for item in rows:
        if (not isinstance(item, dict) or set(item) != {"entry", "path", "sha256", "md5"}
                or not all(isinstance(item[key], str) and item[key] for key in item)):
            raise InputError("invalid addition fields")
        if (not _canonical_relative_path(item["entry"])
                or any(len(item[key]) != size or any(c not in "0123456789abcdef" for c in item[key])
                       for key, size in (("sha256", 64), ("md5", 32)))):
            raise InputError("invalid addition path or digest")
        result.append(Addition(item["entry"], Path(item["path"]), item["sha256"], item["md5"]))
    return result


def _file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verify_command(args):
    import json

    full_enabled = args.full_protection
    origin_args = (args.full_projection_origin_manifest, args.full_projection_original_source,
                   args.full_projection_baseline_source, args.full_projection_approved_intro)
    full_scripts_args = (args.full_projection_scripts_manifest, args.full_projection_scripts_original_sources,
                         args.full_projection_scripts_candidate_sources)
    if any(origin_args) and not all(origin_args):
        raise InputError('all projection origin inputs are required together')
    if any(full_scripts_args) and not all(full_scripts_args):
        raise InputError('all projection script inputs are required together')
    if (args.approved_hints or args.approved_scenes or args.approved_gdc or args.full_scene_manifest or args.full_asset_plan or args.full_asset_godot or any(origin_args)
            or any(full_scripts_args)) and not full_enabled:
        raise InputError('full protection inputs require --full-protection')
    if bool(args.full_asset_plan) != bool(args.full_asset_godot):
        raise InputError('asset plan and Godot binary are required together')
    if args.approved_scenes and not args.full_scene_manifest:
        raise InputError('approved scenes require a full scene manifest')
    if full_enabled:
        if not __package__:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        if args.full_scene_manifest:
            from project.adapters import full_scene_verify
            try:
                full_scene_verify._parse_manifest(args.full_scene_manifest)
            except full_scene_verify.ManifestError as exc:
                raise InputError('invalid scene manifest: ' + str(exc)) from exc
        if args.full_asset_plan:
            from project.adapters import full_asset_verify
            try:
                full_asset_verify.read_plan(args.full_asset_plan)
            except (OSError, full_asset_verify.VerificationError) as exc:
                raise InputError('invalid asset plan: ' + str(exc)) from exc
        if all(full_scripts_args):
            from project.adapters import full_projection_scripts_verify
            try:
                full_projection_scripts_verify.read_manifest(args.full_projection_scripts_manifest)
            except (OSError, full_projection_scripts_verify.VerificationError) as exc:
                raise InputError('invalid projection scripts manifest: ' + str(exc)) from exc
    projection_args = (args.projection_structural_map, args.projection_baseline,
                       args.projection_gdre_dir, args.projection_token_probe)
    if any(value is not None for value in projection_args) and not all(projection_args):
        raise InputError("projection map, baseline PCK, GDRE directory, and token probe are required together")
    projection_enabled = all(projection_args)
    if (all(origin_args) or all(full_scripts_args)) and not projection_enabled:
        raise InputError('full projection verification requires the selected projection inputs')
    if projection_enabled:
        if not __package__:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from project.adapters import projection_payload_verify, script_localize
        try:
            projection_raw, projection_spec = projection_payload_verify.read_manifest(args.projection_structural_map)
            script_localize.check_tools(Path(args.projection_gdre_dir).resolve(), Path(args.projection_token_probe).resolve())
        except (projection_payload_verify.VerificationError, script_localize.LocalizeError) as exc:
            raise InputError(str(exc)) from exc
        projection_manifest_digest = hashlib.sha256(projection_raw).hexdigest()

    gdc_args = (args.gdc_structural_map, args.gdc_gdre_dir, args.gdc_token_probe)
    if any(value is not None for value in gdc_args) and not all(gdc_args):
        raise InputError("GDC structural map, GDRE directory, and token probe are required together")
    gdc_enabled = all(gdc_args)
    if args.approved_gdc and not gdc_enabled:
        raise InputError('approved GDC requires selected GDC verification inputs')
    if gdc_enabled:
        if not __package__:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from project.adapters import gdc_payload_verify, script_localize

        try:
            gdc_raw, gdc_spec = gdc_payload_verify.read_manifest(args.gdc_structural_map)
            script_localize.check_tools(Path(args.gdc_gdre_dir).resolve(), Path(args.gdc_token_probe).resolve())
        except (gdc_payload_verify.ManifestError, script_localize.LocalizeError) as exc:
            raise InputError(str(exc)) from exc
        gdc_manifest_digest = hashlib.sha256(gdc_raw).hexdigest()
    chain_args = (args.replacement_stage, args.replacement_stage_sha256, args.additions)
    if any(value is not None for value in chain_args) and not all(chain_args):
        raise InputError("replacement stage, its SHA-256, and additions are required together")
    chain = all(chain_args)
    mapping_digest = _file_sha256(args.mapping) if chain or args.hint_structural_map is not None or gdc_enabled or projection_enabled or full_enabled else None
    additions_digest = _file_sha256(args.additions) if chain else None
    mapping = _read_mapping(args.mapping)
    localized_dir = Path(args.localized_dir)
    if not localized_dir.is_dir():
        raise InputError("localized directory is not a directory")
    report_path = Path(args.report)
    if report_path.exists():
        raise InputError("report already exists")
    additions = _read_additions(args.additions) if chain else None
    expected = {item["entry"]: item["sha256"] for item in mapping["replacements"]}
    final_payload_sha = _file_sha256(args.payload) if args.hint_structural_map is not None or gdc_enabled or projection_enabled or full_enabled else None
    try:
        for item in mapping["replacements"]:
            if item["source"] == "localized":
                source = _replacement_path(localized_dir, item["file"])
                with source.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                        raise PckError("localized resource does not match the map")
        stage = args.replacement_stage if additions is not None else args.payload
        if additions is not None and _file_sha256(stage) != args.replacement_stage_sha256:
            raise PckError("replacement stage does not match the expected revision")
        resource_report = verify_resource_bytes(
            args.original, stage, expected, expected_original_sha256=mapping["source_sha256"]
        )
        if additions is not None:
            from project.adapters import pck_additions

            try:
                addition_report = pck_additions.verify_additions(
                    stage, args.payload, additions,
                    expected_original_sha256=args.replacement_stage_sha256,
                )
            except pck_additions.PckError as exc:
                raise PckError(str(exc)) from exc
            if (_file_sha256(args.original) != mapping["source_sha256"]
                    or _file_sha256(stage) != args.replacement_stage_sha256
                    or _file_sha256(args.payload) != addition_report["result_sha256"]
                    or _file_sha256(args.mapping) != mapping_digest
                    or _file_sha256(args.additions) != additions_digest):
                raise PckError("PCK or input manifest changed while verifying the resource chain")
        if args.hint_structural_map is not None:
            if not __package__:
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from project.adapters import payload_rsrc_verify

            verified_payload_sha = _file_sha256(args.payload)
            if verified_payload_sha != final_payload_sha:
                raise PckError("final PCK changed during resource verification")
            if additions is not None and verified_payload_sha != addition_report["result_sha256"]:
                raise PckError("final PCK changed before hint verification")
            try:
                hint_report = payload_rsrc_verify.verify_selected_hints(
                    args.original, args.payload, args.mapping, args.hint_structural_map
                )
            except payload_rsrc_verify.funeral.InputError as exc:
                raise InputError(str(exc)) from exc
            except payload_rsrc_verify.VerificationError as exc:
                raise PckError(str(exc)) from exc
            if (hint_report["payload_pck_sha256"] != verified_payload_sha
                    or hint_report["mapping_sha256"] != mapping_digest
                    or _file_sha256(args.original) != mapping["source_sha256"]
                    or _file_sha256(args.payload) != verified_payload_sha
                    or _file_sha256(args.mapping) != mapping_digest):
                raise PckError("PCK or mapping changed during hint verification")
            if additions is not None and (_file_sha256(stage) != args.replacement_stage_sha256
                                          or _file_sha256(args.additions) != additions_digest):
                raise PckError("replacement stage or additions changed during hint verification")
        if gdc_enabled:
            if gdc_spec["source_sha256"] != mapping["source_sha256"] or gdc_spec["payload_sha256"] != final_payload_sha:
                raise PckError("GDC manifest PCK binding mismatch")
            for entry in gdc_spec["entries"]:
                if expected.get(entry["entry"]) != entry["stages"][-1]["candidate_sha256"]:
                    raise PckError("GDC manifest and replacement map differ")
            try:
                gdc_report = gdc_payload_verify.verify(
                    args.original, args.payload, args.gdc_structural_map,
                    args.gdc_gdre_dir, args.gdc_token_probe,
                )
            except gdc_payload_verify.ManifestError as exc:
                raise InputError(str(exc)) from exc
            except (gdc_payload_verify.VerificationError, gdc_payload_verify.funeral.PckError,
                    script_localize.LocalizeError) as exc:
                raise PckError(str(exc)) from exc
            if (gdc_report["manifest_sha256"] != gdc_manifest_digest
                    or gdc_report["payload_sha256"] != final_payload_sha
                    or _file_sha256(args.original) != mapping["source_sha256"]
                    or _file_sha256(args.payload) != final_payload_sha
                    or _file_sha256(args.mapping) != mapping_digest):
                raise PckError("PCK or mapping changed during GDC verification")
            if additions is not None and (_file_sha256(stage) != args.replacement_stage_sha256
                                          or _file_sha256(args.additions) != additions_digest):
                raise PckError("replacement stage or additions changed during GDC verification")
            gdc_report["mapping_sha256"] = mapping_digest
        if projection_enabled:
            if (projection_spec["payload_sha256"] != final_payload_sha
                    or expected.get(projection_spec["entry"]) != projection_spec["payload_entry_sha256"]):
                raise PckError("projection manifest and final PCK mapping differ")
            try:
                projection_report = projection_payload_verify.verify(
                    args.projection_baseline, args.payload, args.projection_structural_map,
                    args.projection_gdre_dir, args.projection_token_probe,
                )
            except (projection_payload_verify.VerificationError, projection_payload_verify.funeral.PckError,
                    script_localize.LocalizeError) as exc:
                raise PckError(str(exc)) from exc
            if (projection_report["manifest_sha256"] != projection_manifest_digest
                    or _file_sha256(args.original) != mapping["source_sha256"]
                    or _file_sha256(args.payload) != final_payload_sha
                    or _file_sha256(args.mapping) != mapping_digest):
                raise PckError("PCK or mapping changed during projection verification")
            if additions is not None and (_file_sha256(stage) != args.replacement_stage_sha256
                                          or _file_sha256(args.additions) != additions_digest):
                raise PckError("replacement stage or additions changed during projection verification")
            projection_report["mapping_sha256"] = mapping_digest
        if full_enabled:
            if not __package__:
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from project.adapters import full_payload_verify

            additional = []
            approved_hint_report = None
            approved_gdc_report = None
            if args.approved_hints:
                from project.adapters import hint_approval_ledger, payload_rsrc_verify
                try:
                    approved_hint_report = hint_approval_ledger.verify(args.original, args.payload, args.mapping)
                except (hint_approval_ledger.LedgerError, payload_rsrc_verify.VerificationError) as exc:
                    raise PckError('approved hints verification: ' + str(exc)) from exc
            if args.approved_gdc:
                from project.adapters import gdc_approval_ledger
                try:
                    approved_gdc_report = gdc_approval_ledger.verify(
                        args.original, args.payload, args.gdc_gdre_dir, args.gdc_token_probe)
                except (gdc_approval_ledger.LedgerError, gdc_payload_verify.VerificationError,
                        script_localize.LocalizeError) as exc:
                    raise PckError('approved GDC verification: ' + str(exc)) from exc
            if args.full_scene_manifest:
                from project.adapters import full_scene_verify
                scene_manifest_sha = _file_sha256(args.full_scene_manifest)
                try:
                    scene_report = full_scene_verify.verify_payload(args.original, args.payload, args.full_scene_manifest)
                except (full_scene_verify.ManifestError, full_scene_verify.VerificationError) as exc:
                    raise PckError('scene protection verification: ' + str(exc)) from exc
                if _file_sha256(args.full_scene_manifest) != scene_manifest_sha:
                    raise PckError('scene protection manifest changed during verification')
                approved_scenes = {}
                if args.approved_scenes:
                    from project.adapters import scene_approval_ledger
                    try:
                        approved_scene_report = scene_approval_ledger.verify(args.original, args.payload)
                    except (OSError, ValueError) as exc:
                        raise PckError('approved scenes verification: ' + str(exc)) from exc
                    approved_scenes = {item['entry']: item for item in approved_scene_report['entries']}
                for item in scene_report['entries']:
                    status = item['status']
                    reason = item.get('reason') or '표시 문자열과 비대상 직렬화 구조 비교'
                    approved = approved_scenes.get(item['entry'], {})
                    if status != 'failed' and approved.get('status') == 'passed':
                        status = 'passed'
                        reason = '고정 승인 배치·장면 위치 및 원본→최종 전체 구조 검증'
                    elif status == 'passed':
                        status = 'unsupported'
                        reason = '구조 비교는 통과했으나 표시 정책의 승인 근거가 독립 결속되지 않음'
                    additional.append({'entry': item['entry'], 'status': status, 'reason': reason})
            if args.full_asset_plan:
                from project.adapters import full_asset_verify
                try:
                    asset_report = full_asset_verify.verify(args.original, args.payload, args.full_asset_plan, args.full_asset_godot)
                except full_asset_verify.VerificationError as exc:
                    raise PckError('asset protection verification: ' + str(exc)) from exc
                for item in asset_report['assets']:
                    status = item['status']
                    reason = item.get('reason') or item.get('scope') or '자산 보호 구조 확인'
                    if status == 'passed' and not item.get('strict_structure_verified', False):
                        status = 'unsupported'
                        reason = '픽셀 부분 검사는 통과했으나 비픽셀 구조 전체는 미검증'
                    elif status == 'passed':
                        status = 'unsupported'
                        reason = '구조 비교는 통과했으나 자산 정책의 승인 근거가 독립 결속되지 않음'
                    additional.append({'entry': item['entry'], 'status': status, 'reason': reason})
            if all(origin_args):
                from project.adapters import projection_origin_verify
                origin_path = Path(args.full_projection_origin_manifest)
                origin_raw = origin_path.read_bytes()
                origin_spec = json.loads(origin_raw.decode('utf-8'), object_pairs_hook=_unique_object)
                try:
                    origin_report = projection_origin_verify.verify(
                        args.original, args.projection_baseline, args.full_projection_original_source,
                        args.full_projection_baseline_source, args.full_projection_approved_intro,
                        origin_path, args.projection_gdre_dir, args.projection_token_probe)
                    if origin_report['manifest_sha256'] != hashlib.sha256(origin_raw).hexdigest():
                        raise full_payload_verify.FullVerificationError('projection origin manifest binding differs')
                    chain = full_payload_verify.projection_chain_result(
                        origin_spec, projection_spec, origin_report, projection_report,
                        original_sha256=mapping['source_sha256'], payload_sha256=final_payload_sha,
                        expected=expected)
                    chain['status'] = 'unsupported'
                    chain['reason'] = '구조 비교는 통과했으나 표시 정책의 승인 근거가 독립 결속되지 않음'
                    additional.append(chain)
                except (OSError, ValueError, KeyError, TypeError, IndexError,
                        script_localize.LocalizeError, full_payload_verify.FullVerificationError) as exc:
                    raise PckError('projection origin verification: ' + str(exc)) from exc
            if all(full_scripts_args):
                from project.adapters import full_projection_scripts_verify
                try:
                    scripts_report = full_projection_scripts_verify.verify(
                        args.original, args.payload, args.full_projection_scripts_original_sources,
                        args.full_projection_scripts_candidate_sources, args.full_projection_scripts_manifest,
                        args.projection_gdre_dir, args.projection_token_probe)
                except (OSError, ValueError, KeyError, TypeError, IndexError,
                        script_localize.LocalizeError) as exc:
                    raise PckError('projection scripts verification: ' + str(exc)) from exc
                for item in scripts_report['entries']:
                    additional.append({'entry': item['entry'], 'status': item['status'],
                                       'reason': item.get('reason') or '승인 표시 치환과 원본·최종 토큰 구조'})
            try:
                full_report = full_payload_verify.classify_entries(
                    expected, hint_report=approved_hint_report if args.approved_hints else (hint_report if args.hint_structural_map is not None else None),
                    gdc_report=gdc_report if gdc_enabled else None, additional=additional,
                    hint_approved=bool(args.approved_hints),
                    gdc_approved_entries=[x['entry'] for x in approved_gdc_report['entries']] if args.approved_gdc else ())
            except full_payload_verify.FullVerificationError as exc:
                raise PckError('full protection classification: ' + str(exc)) from exc
            if (_file_sha256(args.original) != mapping['source_sha256']
                    or _file_sha256(args.payload) != final_payload_sha
                    or _file_sha256(args.mapping) != mapping_digest):
                raise PckError('PCK or mapping changed during full protection verification')
    except PckError as exc:
        report = {"status": "failed", "error": str(exc)}
    else:
        report = {
            "status": "incomplete",
            "resource_bytes": resource_report,
            "remaining": ["protected field and final value verification is not implemented"],
        }
        if additions is not None:
            report["additions"] = addition_report
            report["input_sha256"] = {
                "original_pck": mapping["source_sha256"],
                "mapping": mapping_digest,
                "additions": additions_digest,
            }
        if args.hint_structural_map is not None:
            report["selected_hint_resources"] = hint_report
            report["remaining"] = ["complete protected field and final value verification is not implemented"]
        if gdc_enabled:
            report["selected_gdc_scripts"] = gdc_report
            report["remaining"] = ["complete protected field and final value verification is not implemented"]
        if projection_enabled:
            report["selected_projection"] = projection_report
            report["remaining"] = ["complete protected field and final value verification is not implemented"]
        if full_enabled:
            report['full_protection'] = full_report
            if args.approved_hints:
                report['approved_hints'] = approved_hint_report
            if args.approved_gdc:
                report['approved_gdc'] = approved_gdc_report
            if args.full_scene_manifest:
                report['full_scene'] = scene_report
                if args.approved_scenes:
                    report['approved_scenes'] = approved_scene_report
            if args.full_asset_plan:
                report['full_assets'] = asset_report
            if all(origin_args):
                report['projection_origin'] = origin_report
            if all(full_scripts_args):
                report['full_projection_scripts'] = scripts_report
            report['status'] = full_report['status']
            report['remaining'] = ([] if full_report['status'] == 'passed'
                                   else ['unsupported or failed entries require resolution'])
            if additions is not None:
                report['added_assets_protection'] = [
                    {'entry': item.path, 'status': 'unsupported',
                     'reason': '추가 자산은 바이트만 확인했고 구조·내용 검증은 미지원'}
                    for item in additions
                ]
                if report['status'] != 'failed':
                    report['status'] = 'unsupported'
                report['remaining'].append('added asset structure and content verification is not implemented')
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False))
    # Byte-only and incomplete entry coverage must never return success.
    return 0 if report['status'] == 'passed' else 1


def _write_json(path, value):
    import json

    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _copy_range(source, target, start, length):
    source.seek(start)
    while length:
        block = _read_exact(source, min(length, 1024 * 1024))
        target.write(block)
        length -= len(block)


def _build_preserving_layout(original, payload, index, replacements):
    """Replace PCK entries while retaining the source index and data order."""
    physical = sorted(index.entries.items(), key=lambda item: item[1].offset)
    cursor = index.base
    for _, entry in physical:
        if entry.offset < cursor:
            raise PckError("overlapping PCK entries are not supported")
        cursor = entry.offset + entry.size

    replacement_paths = {item["entry"]: path for item, path in replacements}
    directory_updates = []
    with Path(original).open("rb") as source, Path(payload).open("xb+") as target:
        _copy_range(source, target, 0, index.base)
        cursor = index.base
        for name, entry in physical:
            _copy_range(source, target, cursor, entry.offset - cursor)
            target.write(bytes((entry.offset - target.tell()) % 16))
            output_offset = target.tell()
            if name in replacement_paths:
                md5 = hashlib.md5()
                size = 0
                with replacement_paths[name].open("rb") as replacement:
                    while block := replacement.read(1024 * 1024):
                        target.write(block)
                        md5.update(block)
                        size += len(block)
                digest = md5.digest()
            else:
                _copy_range(source, target, entry.offset, entry.size)
                size = entry.size
                digest = entry.md5
            directory_updates.append((entry.index_offset, output_offset - index.base, size, digest))
            cursor = entry.offset + entry.size
        _copy_range(source, target, cursor, Path(original).stat().st_size - cursor)
        for position, offset, size, digest in directory_updates:
            target.seek(position)
            target.write(struct.pack("<QQ", offset, size))
            target.write(digest)


def _build_command(args):
    import json
    import os
    import shutil
    import subprocess

    mapping = _read_mapping(args.mapping)
    if not Path(args.localized_dir).is_dir() or not Path(args.assets_dir).is_dir():
        raise InputError("replacement directories must exist")
    original = Path(args.pck)
    with original.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != mapping["source_sha256"]:
            raise PckError("source PCK does not match the expected revision")
    index = inspect_pck(original)
    replacements = []
    for item in mapping["replacements"]:
        if item["entry"] not in index.entries:
            raise InputError("replacement entry is not in the source PCK")
        directory = args.localized_dir if item["source"] == "localized" else args.assets_dir
        path = _replacement_path(directory, item["file"])
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise PckError("replacement resource does not match the map")
        replacements.append((item, path))
    out_dir = Path(args.out_dir)
    if replacements and args.gdre and "=" in str(out_dir.resolve()):
        raise InputError("GDRE staging path cannot contain '='")
    out_dir.mkdir()
    payload = out_dir / "funeralforthesun.pck"
    if replacements and not args.gdre:
        _build_preserving_layout(original, payload, index, replacements)
    elif replacements:
        gdre = Path(args.gdre).resolve(strict=True)
        if not gdre.is_file():
            raise InputError("GDRE executable is not a file")
        stage = out_dir / "_build"
        stage.mkdir()
        command = [str(gdre), "--headless", f"--pck-patch={original.resolve()}"]
        for index_number, (item, source) in enumerate(replacements, 1):
            # GDRE keys patch arguments by source path, so each destination
            # needs a distinct staged source even when contents are identical.
            staged = stage / f"{index_number:04d}.bin"
            with staged.open("xb") as dest, source.open("rb") as source_file:
                shutil.copyfileobj(source_file, dest, length=1024 * 1024)
            command.append(f"--patch-file={staged.resolve()}=res://{item['entry']}")
        command.append(f"--output={payload.resolve()}")
        home = stage / "home"
        home.mkdir()
        env = {
            "PATH": os.defpath,
            "HOME": str(home.resolve()),
            "XDG_CONFIG_HOME": str((home / "config").resolve()),
            "XDG_DATA_HOME": str((home / "data").resolve()),
            "XDG_CACHE_HOME": str((home / "cache").resolve()),
        }
        with (stage / "gdre.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, check=False)
        if result.returncode != 0:
            raise PckError(f"GDRE failed with exit code {result.returncode}; see {stage / 'gdre.log'}")
    else:
        with payload.open("xb") as output, original.open("rb") as source:
            shutil.copyfileobj(source, output, length=1024 * 1024)
    expected = {item["entry"]: item["sha256"] for item, _ in replacements}
    resource_report = verify_resource_bytes(
        original, payload, expected, expected_original_sha256=mapping["source_sha256"]
    )
    with payload.open("rb") as stream:
        payload_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    _write_json(out_dir / "changed-resources.json", {"replacements": mapping["replacements"]})
    report = {"status": "resource_bytes_passed", "payload_sha256": payload_sha256, "resource_bytes": resource_report}
    _write_json(out_dir / "payload-report.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main(argv=None):
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-payload", help="check PCK bytes; full semantic verification is pending")
    verify.add_argument("--original", required=True)
    verify.add_argument("--approved-gdc", action="store_true", help="verify selected GDCs against fixed reviewed batch approvals")
    verify.add_argument("--payload", required=True)
    verify.add_argument("--mapping", required=True)
    verify.add_argument("--localized-dir", required=True)
    verify.add_argument("--report", required=True)
    verify.add_argument("--replacement-stage", help="explicit intermediate PCK before additions")
    verify.add_argument("--replacement-stage-sha256", help="expected SHA-256 of the intermediate PCK")
    verify.add_argument("--additions", help="ordered additions JSON used to construct the final PCK")
    verify.add_argument("--hint-structural-map", help="optional structural map for explicitly selected hint resources")
    verify.add_argument("--approved-hints", action="store_true", help="verify hints against fixed reviewed batch approvals")
    verify.add_argument("--approved-scenes", action="store_true", help="verify scenes against fixed reviewed batch approvals")
    verify.add_argument("--gdc-structural-map", help="optional structural map for explicitly selected GDC scripts")
    verify.add_argument("--gdc-gdre-dir", help="pinned GDRE directory for selected GDC verification")
    verify.add_argument("--gdc-token-probe", help="pinned native tokenizer for selected GDC verification")
    verify.add_argument("--projection-structural-map", help="optional appended projection verification manifest")
    verify.add_argument("--projection-baseline", help="baseline PCK for the selected projection comparison")
    verify.add_argument("--projection-gdre-dir", help="pinned GDRE directory for projection verification")
    verify.add_argument("--projection-token-probe", help="pinned native tokenizer for projection verification")
    verify.add_argument('--full-protection', action='store_true', help='classify every replacement by protection verification result')
    verify.add_argument('--full-scene-manifest', help='approved node-string policies and complete changed-scene scope')
    verify.add_argument('--full-asset-plan', help='approved image and font entry scope')
    verify.add_argument('--full-asset-godot', help='pinned official Godot for asset decoding')
    verify.add_argument('--full-projection-origin-manifest', help='original-to-baseline projection manifest')
    verify.add_argument('--full-projection-original-source', help='original projection GDScript source')
    verify.add_argument('--full-projection-baseline-source', help='baseline projection GDScript source')
    verify.add_argument('--full-projection-approved-intro', help='approved initial projection GDScript source')
    verify.add_argument('--full-projection-scripts-manifest', help='approved projection script scope')
    verify.add_argument('--full-projection-scripts-original-sources', help='original projection script sources')
    verify.add_argument('--full-projection-scripts-candidate-sources', help='approved projection script sources')
    build = subparsers.add_parser("build-payload", help="build a PCK from prepared resource replacements")
    build.add_argument("--pck", required=True)
    build.add_argument("--mapping", required=True)
    build.add_argument("--localized-dir", required=True)
    build.add_argument("--assets-dir", required=True)
    build.add_argument("--out-dir", required=True)
    build.add_argument("--gdre", help="optional explicit GDRE packer; default preserves the source PCK layout")
    try:
        args = parser.parse_args(argv)
        return _verify_command(args) if args.command == "verify-payload" else _build_command(args)
    except PckError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    except (InputError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
