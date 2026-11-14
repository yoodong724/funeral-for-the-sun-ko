"""Add new files to an unencrypted standalone Godot 4 PCK, preserving old bytes.

This module only verifies container bytes. It does not validate Godot resource
semantics, runtime loading, localization, save compatibility, or release safety.
Inputs are prepared files with explicit SHA-256 and MD5 hashes. Paths are
canonical, PCK-relative paths; additions are ordered as supplied.
"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import struct
import tempfile

from project.adapters.funeral import (
    PckError,
    _canonical_relative_path,
    _entry_sha256,
    _range_is_zero,
    _read_exact,
    _same_range,
    inspect_pck,
)

_CHUNK = 1024 * 1024
_MAX_U32 = (1 << 32) - 1
_MAX_U64 = (1 << 64) - 1


@dataclass(frozen=True)
class Addition:
    """An expected new PCK path, input file and its exact lowercase hashes."""

    path: str
    source: Path
    sha256: str
    md5: str


def _check_digest(value, length, label):
    if (not isinstance(value, str) or len(value) != length
            or any(char not in "0123456789abcdef" for char in value)):
        raise PckError(f"invalid {label}")


def _hash_file(path):
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0
    try:
        with Path(path).open("rb") as stream:
            while block := stream.read(_CHUNK):
                sha.update(block)
                md5.update(block)
                size += len(block)
    except (OSError, TypeError, ValueError) as exc:
        raise PckError("cannot read input file") from exc
    return size, sha.hexdigest(), md5.hexdigest()


def _prepare_additions(additions, existing):
    if not isinstance(additions, (list, tuple)) or not additions:
        raise PckError("at least one ordered addition is required")
    prepared = []
    names = set(existing)
    directories = set()
    for name in names:
        parts = name.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            if parent in names:
                raise PckError("source file and directory paths conflict")
            directories.add(parent)
    for item in additions:
        if not isinstance(item, Addition) or not _canonical_relative_path(item.path):
            raise PckError("invalid addition or noncanonical relative path")
        parts = item.path.split("/")
        parents = ["/".join(parts[:index]) for index in range(1, len(parts))]
        if item.path in names or item.path in directories or any(parent in names for parent in parents):
            raise PckError("addition path is duplicated or conflicts with a file or directory")
        names.add(item.path)
        directories.update(parents)
        _check_digest(item.sha256, 64, "addition SHA-256")
        _check_digest(item.md5, 32, "addition MD5")
        try:
            name = item.path.encode("utf-8", errors="strict")
            source = Path(item.source)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise PckError("invalid addition path or source") from exc
        if not source.is_file():
            raise PckError("addition source is not a regular file")
        padded_name = name + b"\0" * (-len(name) % 4)
        if len(padded_name) > _MAX_U32:
            raise PckError("addition path is too long")
        size, sha, md5 = _hash_file(source)
        if size > _MAX_U64 or sha != item.sha256 or md5 != item.md5:
            raise PckError("addition source does not match its expected hashes")
        prepared.append((item, source, padded_name, size))
    return prepared


def _source_index(original, expected_sha256):
    _check_digest(expected_sha256, 64, "source PCK SHA-256")
    _, source_sha, _ = _hash_file(original)
    if source_sha != expected_sha256:
        raise PckError("source PCK does not match its expected revision")
    index = inspect_pck(original)
    major, minor, _ = index.engine
    if major > 4 or (major == 4 and minor > 4):
        raise PckError("PCK requires a newer Godot engine")
    with Path(original).open("rb") as stream:
        for entry in index.entries.values():
            _entry_sha256(stream, entry)
    return index


def _copy_range(source, target, start, size):
    source.seek(start)
    while size:
        block = _read_exact(source, min(size, _CHUNK))
        target.write(block)
        size -= len(block)


def _layout(source_index, source_size, prepared):
    if len(source_index.entries) + len(prepared) > _MAX_U32:
        raise PckError("too many PCK entries")
    new_directory_size = sum(4 + len(name) + 36 for _, _, name, _ in prepared)
    new_base = source_index.base + ((new_directory_size + 15) // 16) * 16
    if new_base > _MAX_U64:
        raise PckError("PCK base exceeds supported range")
    position = new_base + source_size - source_index.base
    records = []
    for item, source, padded_name, size in prepared:
        position += -position % 16
        relative = position - new_base
        if relative > _MAX_U64 or position + size > _MAX_U64:
            raise PckError("addition offset exceeds supported range")
        record = (struct.pack("<I", len(padded_name)) + padded_name
                  + struct.pack("<QQ", relative, size)
                  + bytes.fromhex(item.md5) + struct.pack("<I", 0))
        records.append((record, position, item, source, size))
        position += size
    return new_base, records


def verify_additions(original, result, additions, *, expected_original_sha256):
    """Independently verify source, output, and additions without writing files.

    This strictly checks header, original directory bytes, original directory
    padding, the entire original body, added entry order/metadata/data, and
    alignment/padding. An OK result covers PCK bytes only.
    """
    original = Path(original)
    result = Path(result)
    source = _source_index(original, expected_original_sha256)
    prepared = _prepare_additions(additions, source.entries)
    candidate = inspect_pck(result)
    source_size = original.stat().st_size
    result_size = result.stat().st_size
    names = [item.path for item, _, _, _ in prepared]
    if list(candidate.entries) != list(source.entries) + names:
        raise PckError("PCK entry paths or order changed")
    if (candidate.engine, candidate.flags, candidate.reserved) != (source.engine, source.flags, source.reserved):
        raise PckError("PCK header metadata changed")
    # The new directory extends the old one; its growth is rounded to a
    # multiple of 16 so every old physical entry retains its alignment residue.
    directory_growth = candidate.directory_end - source.directory_end
    if directory_growth < 0 or candidate.base != source.base + ((directory_growth + 15) // 16) * 16:
        raise PckError("PCK data base or alignment changed")
    if any((candidate.entries[name].offset - entry.offset) != candidate.base - source.base
           for name, entry in source.entries.items()):
        raise PckError("original entry offsets changed relative to data base")

    with original.open("rb") as old, result.open("rb") as new:
        if not (_same_range(old, 0, new, 0, 24) and _same_range(old, 32, new, 32, 64)):
            raise PckError("PCK header bytes changed")
        if not _same_range(old, 100, new, 100, source.directory_end - 100):
            raise PckError("original index bytes changed")
        original_padding = source.base - source.directory_end
        if not _same_range(old, source.directory_end, new, candidate.directory_end, original_padding):
            raise PckError("original directory padding changed")
        padding_start = candidate.directory_end + original_padding
        if padding_start > candidate.base or not _range_is_zero(new, padding_start, candidate.base - padding_start):
            raise PckError("new directory padding is invalid")
        body_size = source_size - source.base
        if not _same_range(old, source.base, new, candidate.base, body_size):
            raise PckError("original data area changed")
        for name, original_entry in source.entries.items():
            original_hash = _entry_sha256(old, original_entry)
            if _entry_sha256(new, candidate.entries[name]) != original_hash:
                raise PckError("original PCK entry changed")
        position = candidate.base + body_size
        for item, input_path, padded_name, size in prepared:
            target = candidate.entries[item.path]
            expected_offset = position + (-position % 16)
            if (target.offset != expected_offset or target.size != size or target.md5.hex() != item.md5
                    or target.flags != 0 or target.name_bytes != padded_name):
                raise PckError("addition index or alignment differs")
            if not _range_is_zero(new, position, expected_offset - position):
                raise PckError("new data alignment padding is invalid")
            if _entry_sha256(new, target) != item.sha256:
                raise PckError("addition bytes differ")
            with input_path.open("rb") as addition_file:
                if not _same_range(addition_file, 0, new, target.offset, size):
                    raise PckError("addition source bytes differ")
            position = target.offset + size
        if position != result_size:
            raise PckError("unexpected trailing PCK data")
    # Catch input changes between the initial hash and verification reads.
    if _hash_file(original)[1] != expected_original_sha256:
        raise PckError("source PCK changed while verifying")
    _prepare_additions(additions, source.entries)
    return {
        "scope": "bytes_only",
        "original_sha256": expected_original_sha256,
        "result_sha256": _hash_file(result)[1],
        "original_entries": len(source.entries),
        "added_entries": names,
        "resource_semantics": "not_checked",
        "game_runtime": "not_checked",
    }


def add_entries(original, output, additions, *, expected_original_sha256):
    """Create a new PCK with the given additions; never overwrite a path.

    A sibling temporary file is validated with the read-only verifier before an
    atomic, exclusive hard-link publishes the new output name. The original
    index records and entire original data area are copied byte-for-byte.
    """
    original = Path(original)
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    source = _source_index(original, expected_original_sha256)
    prepared = _prepare_additions(additions, source.entries)
    source_size = original.stat().st_size
    new_base, records = _layout(source, source_size, prepared)
    fd, temp_name = tempfile.mkstemp(prefix="." + output.name + ".", suffix=".tmp", dir=output.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as target, original.open("rb") as old:
            header = bytearray(_read_exact(old, 100))
            struct.pack_into("<Q", header, 24, new_base)
            struct.pack_into("<I", header, 96, len(source.entries) + len(prepared))
            target.write(header)
            _copy_range(old, target, 100, source.directory_end - 100)
            for record, _, _, _, _ in records:
                target.write(record)
            _copy_range(old, target, source.directory_end, source.base - source.directory_end)
            if target.tell() > new_base:
                raise PckError("new directory overlaps data")
            target.write(b"\0" * (new_base - target.tell()))
            _copy_range(old, target, source.base, source_size - source.base)
            for _, position, item, input_path, size in records:
                if target.tell() > position:
                    raise PckError("addition overlaps existing data")
                target.write(b"\0" * (position - target.tell()))
                with input_path.open("rb") as addition_file:
                    _copy_range(addition_file, target, 0, size)
        report = verify_additions(original, temp, additions, expected_original_sha256=expected_original_sha256)
        os.link(temp, output)
        return report
    finally:
        temp.unlink(missing_ok=True)
