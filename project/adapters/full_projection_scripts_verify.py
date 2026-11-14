#!/usr/bin/env python3
"""Verify two approved projection-script deltas against actual PCK entries.

The approved source text and projection helper semantics are trusted inputs;
this does not establish full game or save correctness.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile

from project.adapters import funeral, gdc_payload_verify, script_localize


class VerificationError(ValueError):
    pass


SCRIPTS = {
    'Solanor/UI/book/book2/slot_2.gdc': {
        'name': 'slot_2',
        'original_sha256': '7ec1e336b2b85c45236af7776bd69a63b80995e45e23f424a7e91384aaa71f30',
        'candidate_sha256': '9545eb1a3bba21eba4b82c1e85949b95b90819f5d6e3d6aec74add0e2bb3f975',
        'before': 'button.text = first_page_text',
        'after': 'button.text = FlashbackManager.ko_flashback_display(first_page_text)',
    },
    'Solanor/UI/book/book2/flashback_storage_menu.gdc': {
        'name': 'flashback_storage_menu',
        'original_sha256': 'be37416bf5e104cd36e4f4c60167978f3666063e99eb833ff8b825a370d5afb9',
        'candidate_sha256': '9824140ba10ac6f403dc9474cccc0edd155de0bdc17661197d0f8465743a8dc6',
        'before': '\t\tprint(first_page_text)\n',
        'after': '\t\tprint(first_page_text)\n\t\tfirst_page_text = FlashbackManager.ko_flashback_display(first_page_text)\n',
    },
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def check_source(original, candidate, policy):
    """Reverse exactly the approved display edit, comparing all other bytes."""
    before, after = policy['before'].encode(), policy['after'].encode()
    if original.count(before) != 1 or candidate.count(after) != 1:
        raise VerificationError('approved display anchor count mismatch')
    if candidate.replace(after, before, 1) != original:
        raise VerificationError('non-display source changed')


def _identifier_records(data):
    records = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise script_localize.LocalizeError('invalid identifier table')
        size = struct.unpack_from('<I', data, offset)[0]
        end = offset + 4 + 4 * size
        if end > len(data):
            raise script_localize.LocalizeError('invalid identifier table')
        records.append(data[offset:end])
        offset = end
    return records


def _identifier_record(value):
    return struct.pack('<I', len(value)) + b''.join(struct.pack('<I', ord(c) ^ 0xb6b6b6b6) for c in value)


def _find_sequence(tokens, values):
    matches = [i for i in range(len(tokens) - len(values) + 1)
               if [t['literal'] for t in tokens[i:i + len(values)]] == values]
    if len(matches) != 1:
        raise script_localize.LocalizeError('display token anchor ambiguous or missing')
    return matches[0]


def _maps(layout):
    raw = layout['maps']
    count = len(raw) // 16
    if len(raw) != count * 16:
        raise script_localize.LocalizeError('invalid token maps')
    lines = [struct.unpack_from('<II', raw, i * 8) for i in range(count)]
    columns = [struct.unpack_from('<II', raw, (count + i) * 8) for i in range(count)]
    if ([i for i, _ in lines] != [i for i, _ in columns] or
            len({i for i, _ in lines}) != count):
        raise script_localize.LocalizeError('unsupported token map keys')
    tokens = layout['tokens']
    for (idx, line), (_, col) in zip(lines, columns):
        if idx >= len(tokens) or (tokens[idx]['mapped_line'], tokens[idx]['mapped_column']) != (line, col):
            raise script_localize.LocalizeError('decoded token maps differ from serialized maps')
    if sum(t['mapped_line'] != -1 for t in tokens) != count:
        raise script_localize.LocalizeError('unaccounted mapped token')
    return lines, columns


def compare_token_diff(original_probe, candidate_probe, original_source, policy):
    """Check the only permitted token insertions and their deterministic maps."""
    old = script_localize.split_payload(original_probe[1], original_probe[0])
    new = script_localize.split_payload(candidate_probe[1], candidate_probe[0])
    if old['values'] != new['values']:
        raise VerificationError('non-target constant pool changed')
    old_ids, new_ids = _identifier_records(old['ids']), _identifier_records(new['ids'])
    extra = [_identifier_record(x) for x in ('FlashbackManager', 'ko_flashback_display')]
    if (any(x in old_ids or new_ids.count(x) != 1 for x in extra) or
            [x for x in new_ids if x not in extra] != old_ids):
        raise VerificationError('non-target identifier table changed')
    before, after = old['tokens'], new['tokens']
    if policy['name'] == 'slot_2':
        original_seq = ['button', '.', 'text', '=', 'first_page_text']
        projected_seq = ['button', '.', 'text', '=', 'FlashbackManager', '.',
                         'ko_flashback_display', '(', 'first_page_text', ')']
        start = _find_sequence(before, original_seq)
        if _find_sequence(after, projected_seq) != start:
            raise VerificationError('projected token anchor moved')
        removed = set(range(start + 4, start + 8)) | {start + 9}
        added_line = None
    elif policy['name'] == 'flashback_storage_menu':
        original_seq = ['print', '(', 'first_page_text', ')']
        projected_seq = original_seq + ['first_page_text', '=', 'FlashbackManager', '.',
                                        'ko_flashback_display', '(', 'first_page_text', ')']
        start = _find_sequence(before, original_seq)
        if _find_sequence(after, projected_seq) != start:
            raise VerificationError('projected token anchor moved')
        removed = set(range(start + 4, start + 12))
        offset = original_source.index(policy['before'].encode())
        added_line = original_source[:offset].count(b'\n') + 2
        inserted = after[start + 4]
        if (inserted['start_line'], inserted['mapped_line'], inserted['mapped_column']) != (
                added_line, added_line, before[start]['mapped_column']):
            raise VerificationError('inserted display token map changed')
    else:
        raise script_localize.LocalizeError('unsupported script policy')
    source_offset = original_source.index(policy['before'].encode())
    insertion_line = added_line if added_line is not None else original_source[:source_offset].count(b'\n') + 1
    token_types = {'FlashbackManager': 2, 'ko_flashback_display': 2, 'first_page_text': 2,
                   '.': 81, '(': 77, ')': 78, '=': 28}
    for index in sorted(removed):
        token = after[index]
        literal = token['literal']
        if literal not in token_types:
            raise VerificationError('unexpected inserted token')
        literal_type = 21 if token_types[literal] == 2 else 4
        encoded = literal.encode('utf-8')
        serialized = (struct.pack('<II', literal_type, len(encoded)) + encoded + b'\0' * (-len(encoded) % 4)).hex()
        is_mapped_insert = added_line is not None and index == start + 4
        expected_map = (insertion_line, before[start]['mapped_column']) if is_mapped_insert else (-1, -1)
        if ((token['type'], token['literal_type'], token['literal_bytes'], token['start_line']) !=
                (token_types[literal], literal_type, serialized, insertion_line) or
                (token['mapped_line'], token['mapped_column']) != expected_map):
            raise VerificationError('inserted token encoding or map changed')
        word = new['words'][index]
        if token['type'] == 2:
            identifier = word >> 8
            if identifier >= len(new_ids) or new_ids[identifier] != _identifier_record(literal):
                raise VerificationError('inserted identifier index changed')
        elif word != (0x80 | token['type']):
            raise VerificationError('inserted punctuation word changed')
    mapping = [i for i in range(len(after)) if i not in removed]
    if len(mapping) != len(before):
        raise VerificationError('unexpected token count')
    for old_token, index in zip(before, mapping):
        new_token = after[index]
        for field in ('type', 'literal_type', 'literal_bytes', 'mapped_column'):
            if old_token[field] != new_token[field]:
                raise VerificationError('non-target token or column changed')
        old_word, new_word = old['words'][old_token['index']], new['words'][index]
        if old_token['type'] == 2:
            old_id, new_id = old_word >> 8, new_word >> 8
            if (old_id >= len(old_ids) or new_id >= len(new_ids) or
                    old_ids[old_id] != new_ids[new_id] or (old_word & 0xff) != (new_word & 0xff)):
                raise VerificationError('non-target identifier reference changed')
        elif old_word != new_word:
            raise VerificationError('non-target token word changed')
        for field in ('start_line', 'mapped_line'):
            line = old_token[field]
            expected = line + 1 if added_line is not None and line >= added_line else line
            if new_token[field] != expected:
                raise VerificationError('non-target token line changed')
    old_lines, old_cols = _maps(old)
    new_lines, new_cols = _maps(new)
    expected_lines = [(mapping[idx], line + (1 if added_line is not None and line >= added_line else 0))
                      for idx, line in old_lines]
    expected_cols = [(mapping[idx], col) for idx, col in old_cols]
    if added_line is not None:
        expected_lines.append((start + 4, added_line))
        expected_cols.append((start + 4, before[start]['mapped_column']))
        expected_lines.sort(); expected_cols.sort()
    if new_lines != expected_lines or new_cols != expected_cols:
        raise VerificationError('serialized non-target token maps changed')
    return len(removed)


def read_manifest(path):
    raw = Path(path).read_bytes()
    try:
        spec = json.loads(raw.decode('utf-8'), object_pairs_hook=script_localize.object_pairs)
    except (UnicodeError, json.JSONDecodeError, script_localize.LocalizeError) as exc:
        raise VerificationError('invalid manifest JSON') from exc
    if (not isinstance(spec, dict) or set(spec) != {'format', 'original_pck_sha256', 'final_pck_sha256', 'entries'}
            or spec['format'] != 'funeral-projection-scripts-v1' or spec['entries'] != list(SCRIPTS)):
        raise VerificationError('unsupported manifest scope')
    for key in ('original_pck_sha256', 'final_pck_sha256'):
        if not isinstance(spec[key], str) or not re.fullmatch('[0-9a-f]{64}', spec[key]):
            raise VerificationError('invalid PCK digest')
    return raw, spec


def verify(original_pck, final_pck, original_sources, candidate_sources, manifest, gdre, probe):
    raw, spec = read_manifest(manifest)
    packs = tuple(Path(x).resolve() for x in (original_pck, final_pck))
    source_dirs = tuple(Path(x).resolve() for x in (original_sources, candidate_sources))
    gdre, probe = Path(gdre).resolve(), Path(probe).resolve()
    expected = (spec['original_pck_sha256'], spec['final_pck_sha256'])
    if any(script_localize.sha_file(path) != digest for path, digest in zip(packs, expected)):
        raise VerificationError('PCK binding mismatch')
    indices = tuple(funeral.inspect_pck(path) for path in packs)
    try:
        script_localize.check_tools(gdre, probe)
        tool_error = None
    except script_localize.LocalizeError as exc:
        tool_error = str(exc)
    results = []
    snapshots = []
    for entry, policy in SCRIPTS.items():
        try:
            sources = tuple((directory / (policy['name'] + '.gd')).read_bytes() for directory in source_dirs)
            for directory, data, key in zip(source_dirs, sources, ('original_sha256', 'candidate_sha256')):
                if _sha(data) != policy[key]:
                    raise VerificationError('source differs from approved source')
                snapshots.append((directory / (policy['name'] + '.gd'), _sha(data)))
            check_source(*sources, policy)
            blobs = tuple(gdc_payload_verify._entry_bytes(path, index, entry) for path, index in zip(packs, indices))
            if tool_error:
                results.append({'entry': entry, 'status': 'unsupported', 'reason': tool_error})
                continue
            with tempfile.TemporaryDirectory(prefix='projection-scripts-') as temp:
                work = Path(temp)
                for name, source, blob in zip(('original', 'candidate'), sources, blobs):
                    (work / (name + '.gd')).write_bytes(source)
                    (work / (name + '.gdc')).write_bytes(blob)
                    (work / (name + '-out')).mkdir()
                for name, blob in zip(('original', 'candidate'), blobs):
                    compiled = script_localize.compile_source(work, gdre, probe, name, name + '-out')
                    if compiled != blob:
                        raise VerificationError(name + ' compiled bytes differ from actual PCK entry')
                inspected = script_localize.inspect(work, gdre, probe, ['original', 'candidate'])
                inserted_tokens = compare_token_diff(inspected['original'], inspected['candidate'], sources[0], policy)
            results.append({'entry': entry, 'status': 'passed', 'source_delta_restores_original': True,
                            'compiled_bytes_match_actual_pck': True, 'actual_gdc_tokens_decoded': True,
                            'approved_inserted_tokens': inserted_tokens, 'non_target_token_and_map_diff_checked': True})
        except (VerificationError, gdc_payload_verify.VerificationError, OSError, UnicodeError) as exc:
            results.append({'entry': entry, 'status': 'failed', 'reason': str(exc)})
        except script_localize.LocalizeError as exc:
            results.append({'entry': entry, 'status': 'unsupported', 'reason': str(exc)})
        except (KeyError, IndexError, TypeError, struct.error) as exc:
            results.append({'entry': entry, 'status': 'unsupported', 'reason': 'unsupported token layout: ' + str(exc)})
    if (Path(manifest).read_bytes() != raw or
            any(script_localize.sha_file(path) != digest for path, digest in zip(packs, expected)) or
            any(script_localize.sha_file(path) != digest for path, digest in snapshots)):
        raise VerificationError('input changed during verification')
    if tool_error is None:
        script_localize.check_tools(gdre, probe)
    status = ('failed' if any(x['status'] == 'failed' for x in results) else
              'incomplete' if any(x['status'] != 'passed' for x in results) else 'passed')
    return {'status': status, 'entries': results, 'manifest_sha256': _sha(raw),
            'limitations': ['승인된 소스와 표시 helper의 의미는 신뢰 입력이다.',
                            '다른 GDC·전체 게임 동작·정답·저장과 Windows는 검증하지 않았다.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original-pck', 'final-pck', 'original-sources', 'candidate-sources', 'manifest', 'gdre-dir', 'token-probe'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.original_pck, args.final_pck, args.original_sources, args.candidate_sources,
                        args.manifest, args.gdre_dir, args.token_probe)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'passed' else 1
    except (OSError, ValueError, KeyError, TypeError, script_localize.LocalizeError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
