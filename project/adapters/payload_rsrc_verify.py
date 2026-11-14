"""Verify direct RSRC String changes against the actual bytes in two PCKs.

This is a partial structural check. It does not authorize display locations,
validate PackedScene node pools, scripts, assets, translation or gameplay.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

if __package__:
    from . import funeral, rsrc_inspect
else:
    import funeral
    import rsrc_inspect


MAX_RESOURCE_BYTES = 64 * 1024 * 1024
HASH = re.compile(r'[0-9a-f]{64}\Z')


class VerificationError(ValueError):
    """The packs or requested structural changes do not match."""


def _sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _file_state(path):
    info = Path(path).stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _check_unchanged(path, initial_state, expected_sha256):
    if _file_state(path) != initial_state or _sha_file(path) != expected_sha256 or _file_state(path) != initial_state:
        raise VerificationError('input changed during verification')


def _resource_entry(name):
    return name.casefold().endswith(('.scn', '.res'))


def _validated_entries(spec):
    if not isinstance(spec, dict) or set(spec) != {'format', 'source_sha256', 'payload_sha256', 'entries'}:
        raise VerificationError('invalid structural map fields')
    if spec['format'] != 'funeral-rsrc-structural-map-v1':
        raise VerificationError('unsupported structural map')
    for key in ('source_sha256', 'payload_sha256'):
        if not isinstance(spec[key], str) or not HASH.fullmatch(spec[key]):
            raise VerificationError('invalid pack hash')
    if not isinstance(spec['entries'], list):
        raise VerificationError('invalid structural entries')
    entries = {}
    for item in spec['entries']:
        if not isinstance(item, dict) or set(item) != {'entry', 'changes'}:
            raise VerificationError('invalid structural entry')
        name = item['entry']
        if not funeral._canonical_relative_path(name) or not _resource_entry(name) or name in entries:
            raise VerificationError('invalid or duplicate structural entry')
        if not isinstance(item['changes'], list) or not item['changes']:
            raise VerificationError('resource needs at least one String change')
        changes = []
        for change in item['changes']:
            if not isinstance(change, dict) or set(change) != {'resource_id', 'property', 'path', 'original', 'replacement'}:
                raise VerificationError('invalid String change fields')
            identity, prop = change['resource_id'], change['property']
            original, replacement, path = change['original'], change['replacement'], change['path']
            if (not isinstance(identity, str) or not identity or not isinstance(prop, str) or not prop
                    or not isinstance(original, str) or not isinstance(replacement, str)
                    or original == replacement or not isinstance(path, list)):
                raise VerificationError('invalid String change')
            # A PackedScene variant can be shared by display and protected uses.
            # A serialized pool index alone is not proof that all uses are safe.
            if prop == '_bundled':
                raise VerificationError('PackedScene pool edits need node-use verification')
            steps = []
            for step in path:
                if (not isinstance(step, list) or len(step) != 2 or step[0] not in ('array', 'dict_value')
                        or type(step[1]) is not int or step[1] < 0):
                    raise VerificationError('invalid String change path')
                steps.append((step[0], step[1]))
            changes.append(rsrc_inspect.StringChange(identity, prop, tuple(steps), original, replacement))
        entries[name] = changes
    return entries


def _read_resource(stream, entry):
    if entry.size > MAX_RESOURCE_BYTES:
        raise VerificationError('resource exceeds the supported size')
    stream.seek(entry.offset)
    result = stream.read(entry.size)
    if len(result) != entry.size:
        raise VerificationError('truncated resource entry')
    return result


def verify_selected_hints(original, payload, mapping_path, structural_map_path):
    """Check only explicitly listed hint resources in the actual final PCK.

    The caller remains responsible for full PCK byte verification. This check
    neither establishes coverage of all hints nor validates game behavior.
    """
    paths = {'source_pck': Path(original), 'payload_pck': Path(payload),
             'mapping': Path(mapping_path), 'structural_map': Path(structural_map_path)}
    states = {name: _file_state(path) for name, path in paths.items()}
    mapping_bytes = paths['mapping'].read_bytes()
    structural_bytes = paths['structural_map'].read_bytes()
    mapping_sha = hashlib.sha256(mapping_bytes).hexdigest()
    structural_sha = hashlib.sha256(structural_bytes).hexdigest()
    try:
        spec = json.loads(structural_bytes, object_pairs_hook=funeral._unique_object)
        entries = _validated_entries(spec)
        if not entries:
            raise VerificationError('hint structural map must not be empty')
        for name, changes in entries.items():
            if not name.casefold().endswith('.res'):
                raise VerificationError('hint structural entries must be resources')
            if any(c.property_name not in ('hint_question', 'hint_room_reveal') or c.path for c in changes):
                raise VerificationError('only direct hint display strings are permitted')
        with tempfile.TemporaryDirectory(prefix='funeral-hint-map-') as temporary:
            snapshot = Path(temporary) / 'mapping.json'
            snapshot.write_bytes(mapping_bytes)
            mapping = funeral._read_mapping(snapshot)
        if mapping['source_sha256'] != spec['source_sha256']:
            raise VerificationError('source revisions differ')
        expected = {item['entry']: item['sha256'] for item in mapping['replacements']}
        if not entries.keys() <= expected.keys():
            raise VerificationError('hint resource is not a mapped replacement')
        if _sha_file(original) != spec['source_sha256'] or _sha_file(payload) != spec['payload_sha256']:
            raise VerificationError('pack hash differs')
        source_index, output_index = funeral.inspect_pck(original), funeral.inspect_pck(payload)
        if source_index.engine != (4, 4, 1) or output_index.engine != (4, 4, 1):
            raise VerificationError('unsupported pack engine')
        details = []
        with Path(original).open('rb') as before, Path(payload).open('rb') as after:
            for name, changes in entries.items():
                if name not in source_index.entries or name not in output_index.entries:
                    raise VerificationError('hint resource missing from pack')
                old_bytes = _read_resource(before, source_index.entries[name])
                new_bytes = _read_resource(after, output_index.entries[name])
                actual = hashlib.sha256(new_bytes).hexdigest()
                if actual != expected[name]:
                    raise VerificationError('hint resource differs from replacement map')
                rsrc_inspect.compare_rsrc(old_bytes, new_bytes, changes=changes)
                protected = {'hint_answer', 'first_name', 'last_name', 'has_been_seen',
                             'relevant_chapter', 'connection_data', 'connection_portrait',
                             'combine_integer'}
                resources = {item.identity: item for item in rsrc_inspect._parse(old_bytes).resources}
                for identity in {change.resource_id for change in changes}:
                    if identity not in resources or not protected <= {p.name for p in resources[identity].properties}:
                        raise VerificationError('selected hint lacks required protected fields')
                details.append({'entry': name, 'source_sha256': hashlib.sha256(old_bytes).hexdigest(),
                                'payload_sha256': actual, 'listed_strings': len(changes)})
        for name, sha in (('source_pck', spec['source_sha256']), ('payload_pck', spec['payload_sha256']),
                          ('mapping', mapping_sha), ('structural_map', structural_sha)):
            _check_unchanged(paths[name], states[name], sha)
    except (funeral.PckError, rsrc_inspect.RsrcError) as exc:
        raise VerificationError(str(exc)) from exc
    return {'status': 'partial', 'scope': 'selected_hint_resources_only',
            'entries_checked': len(details), 'listed_strings': sum(x['listed_strings'] for x in details),
            'entries': details, 'source_pck_sha256': spec['source_sha256'],
            'payload_pck_sha256': spec['payload_sha256'], 'mapping_sha256': mapping_sha,
            'structural_map_sha256': structural_sha}


def verify_partial(original, payload, mapping_path, structural_map_path):
    """Check all PCK entries and direct String edits in changed RSRC entries.

    An inspected String location is not necessarily a display-only location.
    Changes outside RSRC, protected game logic and translation remain unchecked.
    """
    paths = {'source_pck': Path(original), 'payload_pck': Path(payload),
             'mapping': Path(mapping_path), 'structural_map': Path(structural_map_path)}
    initial_states = {name: _file_state(path) for name, path in paths.items()}
    mapping_bytes = paths['mapping'].read_bytes()
    structural_bytes = paths['structural_map'].read_bytes()
    mapping_sha256 = hashlib.sha256(mapping_bytes).hexdigest()
    structural_sha256 = hashlib.sha256(structural_bytes).hexdigest()
    try:
        structural_map = json.loads(structural_bytes, object_pairs_hook=funeral._unique_object)
        entries = _validated_entries(structural_map)
        # Reuse the existing mapping parser on the exact bytes being recorded.
        with tempfile.TemporaryDirectory(prefix='funeral-map-') as temporary:
            snapshot = Path(temporary) / 'mapping.json'
            snapshot.write_bytes(mapping_bytes)
            mapping = funeral._read_mapping(snapshot)
        if structural_map['source_sha256'] != mapping['source_sha256']:
            raise VerificationError('source revisions differ')
        if _sha_file(payload) != structural_map['payload_sha256']:
            raise VerificationError('payload hash differs')
        expected = {item['entry']: item['sha256'] for item in mapping['replacements']}
        byte_report = funeral.verify_resource_bytes(original, payload, expected,
                                                     expected_original_sha256=mapping['source_sha256'])
        source_index, output_index = funeral.inspect_pck(original), funeral.inspect_pck(payload)
        if source_index.engine != (4, 4, 1) or output_index.engine != (4, 4, 1):
            raise VerificationError('unsupported pack engine')
        changed_resources = {name for name in byte_report['changed_entries'] if _resource_entry(name)}
        if set(entries) != changed_resources:
            raise VerificationError('structural map does not cover exactly the changed scene/resource entries')
        details = []
        with Path(original).open('rb') as before, Path(payload).open('rb') as after:
            for name, changes in entries.items():
                old_bytes = _read_resource(before, source_index.entries[name])
                new_bytes = _read_resource(after, output_index.entries[name])
                rsrc_inspect.compare_rsrc(old_bytes, new_bytes, changes=changes)
                details.append({'entry': name, 'source_sha256': hashlib.sha256(old_bytes).hexdigest(),
                                'payload_sha256': hashlib.sha256(new_bytes).hexdigest(),
                                'listed_strings': len(changes)})
        for name, expected_sha256 in (
            ('source_pck', mapping['source_sha256']), ('payload_pck', structural_map['payload_sha256']),
            ('mapping', mapping_sha256), ('structural_map', structural_sha256),
        ):
            _check_unchanged(paths[name], initial_states[name], expected_sha256)
    except (funeral.InputError, funeral.PckError, rsrc_inspect.RsrcError) as exc:
        raise VerificationError(str(exc)) from exc
    return {'status': 'partial', 'resource_bytes': byte_report,
            'inputs': {'source_pck_sha256': mapping['source_sha256'],
                       'payload_pck_sha256': structural_map['payload_sha256'],
                       'mapping_sha256': mapping_sha256, 'structural_map_sha256': structural_sha256},
            'rsrc': {'scope': 'serialized_structure_only', 'entries_checked': len(details),
                     'listed_strings': sum(item['listed_strings'] for item in details),
                     'entries': details},
            'remaining': ['display-only authorization and accepted translation mapping',
                          'PackedScene pool, script, image and font semantics as applicable',
                          'runtime, game, save and Windows verification']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True)
    parser.add_argument('--payload', required=True)
    parser.add_argument('--mapping', required=True)
    parser.add_argument('--structural-map', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    try:
        report = verify_partial(args.original, args.payload, args.mapping, args.structural_map)
        with Path(args.report).open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    except (VerificationError, funeral.InputError) as exc:
        print('validation failed:', exc, file=sys.stderr)
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print('input error:', exc, file=sys.stderr)
        return 2
    print(json.dumps({'status': report['status'], 'entries_checked': report['rsrc']['entries_checked'],
                      'listed_strings': report['rsrc']['listed_strings']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
