"""Fail-closed comparison of a supported subset of Godot 4.4 RSRC files.

Only uncompressed, little-endian Godot 4.4 format-6 resources with named
internal resources, UID-bearing dependency tables, and no import metadata are
accepted. Comparison preserves all serialized bytes except explicitly
authorized standalone String variants and validated internal table offsets.
It does not evaluate scripts, runtime state, or game semantics.
"""

from dataclasses import dataclass
import struct


class RsrcError(ValueError):
    """The resource is unsupported, malformed, or differs unexpectedly."""


@dataclass(frozen=True)
class StringChange:
    """One authorized String variant, identified by its serialized location.

    ``resource_id`` is the exact internal resource table path; ``path`` is a
    tuple of (``array``, index) or (``dict_value``, index) steps. Dictionary
    positions are serialized order. Dictionary keys cannot be edited.
    Both original and replacement must match exactly, and every authorization
    must be consumed exactly once.
    """

    resource_id: str
    property_name: str
    path: tuple[tuple[str, int], ...]
    original: str
    replacement: str


@dataclass(frozen=True)
class _Variant:
    tag: int
    raw: bytes
    text: str | None = None
    prefix: bytes = b""
    children: tuple[tuple[tuple[str, int], "_Variant"], ...] = ()


@dataclass(frozen=True)
class _Property:
    name: str
    name_raw: bytes
    value: _Variant


@dataclass(frozen=True)
class _Resource:
    identity: str
    identity_raw: bytes
    kind_raw: bytes
    properties: tuple[_Property, ...]


@dataclass(frozen=True)
class _Document:
    header: bytes
    strings: bytes
    external: bytes
    resources: tuple[_Resource, ...]


class _Reader:
    def __init__(self, data):
        if not isinstance(data, bytes):
            raise RsrcError("resource input must be bytes")
        self.data = data
        self.pos = 0
        self.names = ()
        self.internal_count = 0
        self.external_count = 0
        self.current_resource = 0
        self.real_size = 4

    def take(self, count):
        if count < 0 or count > len(self.data) - self.pos:
            raise RsrcError("truncated resource")
        start = self.pos
        self.pos += count
        return self.data[start:self.pos]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.take(8))[0]

    def string_payload(self, length):
        if length == 0:
            return ""
        raw = self.take(length)
        if raw[-1:] != b"\0" or b"\0" in raw[:-1]:
            raise RsrcError("unsupported noncanonical resource string")
        try:
            return raw[:-1].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RsrcError("invalid UTF-8 resource string") from exc

    def string(self):
        return self.string_payload(self.u32())

    def name(self):
        index = self.u32()
        if index & 0x80000000:
            return self.string_payload(index & 0x7FFFFFFF)
        if index >= len(self.names):
            raise RsrcError("string table index out of bounds")
        return self.names[index]

    def count(self, minimum_bytes):
        value = self.u32()
        if value > (len(self.data) - self.pos) // minimum_bytes:
            raise RsrcError("impossible element count")
        return value

    def variant(self, depth=0):
        if depth > 128:
            raise RsrcError("unsupported Variant nesting depth")
        start = self.pos
        tag = self.u32()
        text_value = None
        children = []
        prefix = b""
        real_width = self.real_size
        fixed = {
            1: 0, 2: 4, 3: 4, 4: real_width, 10: 2 * real_width,
            11: 4 * real_width, 12: 3 * real_width, 13: 4 * real_width,
            14: 4 * real_width, 15: 6 * real_width, 16: 9 * real_width,
            17: 12 * real_width, 18: 6 * real_width, 20: 16, 23: 4,
            40: 8, 41: 8, 42: 0, 43: 0, 45: 8, 46: 16, 47: 12,
            50: 4 * real_width, 51: 16, 52: 16 * real_width,
        }
        packed = {
            32: 4, 33: 4, 35: 3 * real_width, 36: 16, 37: 2 * real_width,
            48: 8, 49: 8, 53: 4 * real_width,
        }
        if tag in fixed:
            self.take(fixed[tag])
        elif tag in (5, 44):
            text_value = self.string()
        elif tag == 22:
            names = self.u16()
            subnames = self.u16() & 0x7FFF
            if names + subnames > (len(self.data) - self.pos) // 4:
                raise RsrcError("impossible NodePath length")
            for _ in range(names + subnames):
                self.name()
        elif tag == 24:
            subtype = self.u32()
            if subtype == 0:
                pass
            elif subtype == 1:
                if not self.string() or not self.string():
                    raise RsrcError("empty legacy external reference")
            elif subtype == 2:
                index = self.u32()
                if index >= self.internal_count or index > self.current_resource:
                    raise RsrcError("invalid or forward internal reference")
                if index == self.current_resource == self.internal_count - 1:
                    raise RsrcError("main resource self-reference is not cached")
            elif subtype == 3:
                if self.u32() >= self.external_count:
                    raise RsrcError("external reference index out of bounds")
            else:
                raise RsrcError("unsupported object reference subtype")
        elif tag in (26, 30):
            count_word = self.u32()
            count = count_word & 0x7FFFFFFF
            entries = count * (2 if tag == 26 else 1)
            if entries > (len(self.data) - self.pos) // 4:
                raise RsrcError("impossible Variant container length")
            prefix = self.data[start:self.pos]
            for index in range(count):
                if tag == 30:
                    children.append((("array", index), self.variant(depth + 1)))
                else:
                    children.append((("dict_key", index), self.variant(depth + 1)))
                    children.append((("dict_value", index), self.variant(depth + 1)))
        elif tag == 31:
            count = self.u32()
            self.take(count)
            self.take((-count) % 4)
        elif tag in packed:
            count = self.count(packed[tag])
            self.take(count * packed[tag])
        elif tag == 34:
            count = self.count(4)
            for _ in range(count):
                self.string()
        else:
            raise RsrcError("unsupported Variant tag")
        return _Variant(tag, self.data[start:self.pos], text_value, prefix, tuple(children))


def _parse(data):
    reader = _Reader(data)
    magic = reader.take(4)
    if magic == b"RSCC":
        raise RsrcError("compressed RSCC is unsupported")
    if magic != b"RSRC":
        raise RsrcError("not an RSRC resource")
    big_endian, real64, major, minor, version = (reader.u32() for _ in range(5))
    if (big_endian, real64, major, minor, version) != (0, 0, 4, 4, 6):
        raise RsrcError("unsupported Godot resource version or byte order")
    if not reader.string():
        raise RsrcError("empty root resource type")
    if reader.u64() != 0:
        raise RsrcError("import metadata offsets are unsupported")
    flags = reader.u32()
    if flags & ~15 or flags & 3 != 3:
        raise RsrcError("unsupported RSRC format flags")
    reader.real_size = 8 if flags & 4 else 4
    reader.u64()  # Root UID: retained in the compared header bytes.
    if flags & 8:
        reader.string()
    reader.take(44)
    header = data[:reader.pos]

    start = reader.pos
    string_count = reader.count(4)
    names = tuple(reader.string() for _ in range(string_count))
    reader.names = names
    strings = data[start:reader.pos]

    start = reader.pos
    external_count = reader.count(16)
    reader.external_count = external_count
    for _ in range(external_count):
        if not reader.string() or not reader.string():
            raise RsrcError("empty external resource type or path")
        reader.u64()
    external = data[start:reader.pos]

    internal_count = reader.count(12)
    if internal_count == 0:
        raise RsrcError("resource has no internal records")
    reader.internal_count = internal_count
    table = []
    identities = set()
    for index in range(internal_count):
        start = reader.pos
        identity = reader.string()
        identity_raw = data[start:reader.pos]
        if not identity or identity in identities:
            raise RsrcError("empty or duplicate internal resource identity")
        if index < internal_count - 1:
            if not identity.startswith("local://"):
                raise RsrcError("nonlocal internal resource identity is unsupported")
            local_id = identity.removeprefix("local://")
            if not local_id or local_id in (".", "..") or any(c in local_id for c in ("/", "\\", ":")):
                raise RsrcError("noncanonical internal resource identity")
        identities.add(identity)
        table.append((identity, identity_raw, reader.u64()))

    resources = []
    for index, (identity, identity_raw, offset) in enumerate(table):
        if offset != reader.pos:
            raise RsrcError("internal resource offset does not point to its ordered record")
        reader.current_resource = index
        start = reader.pos
        if not reader.string():
            raise RsrcError("empty internal resource type")
        kind_raw = data[start:reader.pos]
        property_count = reader.count(8)
        properties = []
        used_names = set()
        for _ in range(property_count):
            start = reader.pos
            name = reader.name()
            name_raw = data[start:reader.pos]
            if not name or name in used_names:
                raise RsrcError("empty or duplicate property name")
            used_names.add(name)
            properties.append(_Property(name, name_raw, reader.variant()))
        resources.append(_Resource(identity, identity_raw, kind_raw, tuple(properties)))
    if reader.take(4) != b"RSRC" or reader.pos != len(data):
        raise RsrcError("invalid resource trailer or unexamined data")
    return _Document(header, strings, external, tuple(resources))


def _change_map(changes):
    try:
        entries = tuple(changes)
    except TypeError as exc:
        raise RsrcError("changes must be an iterable of StringChange") from exc
    result = {}
    for change in entries:
        if not isinstance(change, StringChange):
            raise RsrcError("invalid StringChange")
        if (not isinstance(change.resource_id, str) or not change.resource_id
                or not isinstance(change.property_name, str) or not change.property_name
                or not isinstance(change.original, str) or not isinstance(change.replacement, str)
                or not isinstance(change.path, tuple)):
            raise RsrcError("invalid StringChange fields")
        for step in change.path:
            if (not isinstance(step, tuple) or len(step) != 2
                    or step[0] not in ("array", "dict_value")
                    or type(step[1]) is not int or step[1] < 0):
                raise RsrcError("invalid StringChange path")
        key = (change.resource_id, change.property_name, change.path)
        if key in result:
            raise RsrcError("duplicate StringChange location")
        result[key] = change
    return result


def _compare_variant(before, after, key, allowed, used):
    if before.tag != after.tag:
        raise RsrcError("Variant tag changed")
    change = allowed.get(key)
    if change is not None:
        if before.tag != 5 or before.text != change.original or after.text != change.replacement:
            raise RsrcError("authorized String does not match its exact source and replacement")
        used.add(key)
        return
    if before.tag in (26, 30):
        if before.prefix != after.prefix or len(before.children) != len(after.children):
            raise RsrcError("Variant container length or flags changed")
        for (step, old), (new_step, new) in zip(before.children, after.children):
            if step != new_step:
                raise RsrcError("Variant container order changed")
            _compare_variant(old, new, (key[0], key[1], key[2] + (step,)), allowed, used)
    elif before.raw != after.raw:
        raise RsrcError("unapproved Variant payload change")


def compare_rsrc(original, candidate, *, changes=()):
    """Return True only if supported RSRCs differ solely at allowed Strings.

    Both inputs are bytes. Invalid offsets, unknown formats, missing requested
    locations, and all unapproved structural or byte changes raise RsrcError.
    This is a serialized-structure check, not a runtime or translation check.
    """
    allowed = _change_map(changes)
    before = _parse(original)
    after = _parse(candidate)
    if before.header != after.header:
        raise RsrcError("resource header or root UID changed")
    if before.strings != after.strings:
        raise RsrcError("string table changed")
    if before.external != after.external:
        raise RsrcError("external resource table or order changed")
    if len(before.resources) != len(after.resources):
        raise RsrcError("internal resource count changed")
    used = set()
    for old, new in zip(before.resources, after.resources):
        if old.identity_raw != new.identity_raw or old.kind_raw != new.kind_raw:
            raise RsrcError("internal resource identity, order, or type changed")
        if len(old.properties) != len(new.properties):
            raise RsrcError("property count changed")
        for old_prop, new_prop in zip(old.properties, new.properties):
            if old_prop.name_raw != new_prop.name_raw:
                raise RsrcError("property identity or order changed")
            _compare_variant(old_prop.value, new_prop.value, (old.identity, old_prop.name, ()), allowed, used)
    if used != allowed.keys():
        raise RsrcError("authorized String location was not encountered")
    return True
