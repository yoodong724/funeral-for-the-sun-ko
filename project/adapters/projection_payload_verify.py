#!/usr/bin/env python3
"""Verify a flashback projection against two actual PCK entries.

The manifest supplies the baseline, approved unit-to-pair mappings and changes.
It does not establish the correctness of the baseline or untranslated IDs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from project.adapters import funeral, gdc_payload_verify, script_localize


class VerificationError(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_manifest(path):
    raw = Path(path).read_bytes()
    spec = json.loads(raw.decode('utf-8'), object_pairs_hook=script_localize.object_pairs)
    fields = {'format', 'baseline_sha256', 'payload_sha256', 'entry', 'baseline_entry_sha256', 'payload_entry_sha256', 'units', 'append'}
    if not isinstance(spec, dict) or set(spec) not in (fields, fields | {'replace'}) or spec['format'] != 'funeral-projection-append-v1':
        raise VerificationError('invalid projection manifest')
    for key in ('baseline_sha256', 'payload_sha256', 'baseline_entry_sha256', 'payload_entry_sha256'):
        if not isinstance(spec[key], str) or not re.fullmatch(r'[a-f0-9]{64}', spec[key]):
            raise VerificationError('invalid projection digest')
    if not funeral._canonical_relative_path(spec['entry']) or not spec['entry'].endswith('.gdc'):
        raise VerificationError('invalid projection entry')
    units = spec['units']
    if not isinstance(units, list) or not units:
        raise VerificationError('empty projection units')
    seen = set()
    for row in units:
        if not isinstance(row, dict) or set(row) != {'id', 'source', 'target'} or not all(isinstance(row[k], str) and row[k] for k in row):
            raise VerificationError('invalid projection unit')
        if row['id'] in seen:
            raise VerificationError('duplicate projection unit')
        seen.add(row['id'])
    pairs = spec['append']
    if not isinstance(pairs, list) or not pairs or any(not isinstance(x, list) or len(x) != 2 or not all(isinstance(v, str) and v for v in x) for x in pairs):
        raise VerificationError('invalid appended pairs')
    if len({tuple(x) for x in pairs}) != len(pairs):
        raise VerificationError('duplicate appended pairs')
    replacements = spec.get('replace', [])
    if not isinstance(replacements, list):
        raise VerificationError('invalid replacements')
    seen_sources = set()
    for row in replacements:
        if (not isinstance(row, dict) or set(row) != {'source', 'original', 'replacement'}
                or not all(isinstance(row[k], str) and row[k] for k in row)
                or row['original'] == row['replacement']):
            raise VerificationError('invalid replacement')
        if row['source'] in seen_sources:
            raise VerificationError('duplicate replacement source')
        seen_sources.add(row['source'])
    return raw, spec


def projection(tokens):
    """Parse the specific generated constant, requiring the original token grammar."""
    prefix = [(59, 'extends'), (2, 'Control'), (57, 'const'), (2, '_KO_INTRO_DISPLAY_PAIRS'), (28, '='), (73, '[')]
    if len(tokens) < len(prefix) or [(x['type'], x.get('literal')) for x in tokens[:6]] != prefix:
        raise VerificationError('projection constant header mismatch')
    out, i = [], 6
    while i < len(tokens) and tokens[i]['type'] != 74:
        if i + 4 >= len(tokens) or [x['type'] for x in tokens[i:i+5]] != [73, 3, 79, 3, 74]:
            raise VerificationError('invalid projection pair tokens')
        source, target = tokens[i+1].get('literal'), tokens[i+3].get('literal')
        if tokens[i+1].get('literal_type') != 4 or tokens[i+3].get('literal_type') != 4:
            raise VerificationError('projection pair must contain string Variants')
        if not isinstance(source, str) or not isinstance(target, str):
            raise VerificationError('invalid projection pair literal')
        out.append((source, target)); i += 5
        if i < len(tokens) and tokens[i]['type'] == 79:
            i += 1
        elif i >= len(tokens) or tokens[i]['type'] != 74:
            raise VerificationError('invalid projection separator')
    if i >= len(tokens) or not out:
        raise VerificationError('missing projection terminator')
    return out, i


def compare(before, after, spec):
    if before['ids'] != after['ids']:
        raise VerificationError('identifier table changed')
    bt, at = before['tokens'], after['tokens']
    bp, close = projection(bt); ap, _ = projection(at)
    added = [tuple(x) for x in spec['append']]
    replacements = {x['source']: (x['original'], x['replacement']) for x in spec.get('replace', [])}
    if len({s for s, _ in bp}) != len(bp):
        raise VerificationError('duplicate baseline projection source')
    indices = {}
    revised = []
    for index, (source, target) in enumerate(bp):
        if source in replacements:
            original, replacement = replacements[source]
            if target != original:
                raise VerificationError('replacement original mismatch')
            indices[6 + 6 * index + 3] = (original, replacement)
            target = replacement
        revised.append((source, target))
    if len(indices) != len(replacements):
        raise VerificationError('replacement source missing from baseline')
    if ap != revised + added:
        raise VerificationError('projection additions differ')
    expected = {(x['source'], x['target']) for x in spec['units']}
    if not set(added).issubset(expected):
        raise VerificationError('appended pair is not assigned to a unit')
    if not {(source, value[1]) for source, value in replacements.items()}.issubset(expected):
        raise VerificationError('replacement is not assigned to a unit')
    if not expected.issubset(set(ap)):
        raise VerificationError('unit projection missing or changed')
    if len(set(s for s, _ in ap)) != len(ap):
        raise VerificationError('duplicate projection source')
    extra = at[close:close + 6 * len(added)]
    if len(extra) != 6 * len(added):
        raise VerificationError('appended token count mismatch')
    for i, (source, target) in enumerate(added):
        row = extra[6*i:6*i+6]
        if [x['type'] for x in row] != [79, 73, 3, 79, 3, 74] or row[2].get('literal') != source or row[4].get('literal') != target:
            raise VerificationError('appended token mismatch')
    remaining = at[:close] + at[close + len(extra):]
    if len(remaining) != len(bt):
        raise VerificationError('non-target token count mismatch')
    boundary = bt[close - 1]['start_line']
    for index, (old, new) in enumerate(zip(bt, remaining)):
        if any(old.get(k) != new.get(k) for k in ('type', 'literal_type', 'mapped_column')):
            raise VerificationError('non-target token or column changed')
        if index in indices:
            original, replacement = indices[index]
            if old['type'] != 3 or old.get('literal_type') != 4 or old.get('literal') != original or new.get('literal') != replacement:
                raise VerificationError('replacement token mismatch')
        elif old.get('literal_bytes') != new.get('literal_bytes'):
            raise VerificationError('non-target token or column changed')
        for key in ('start_line', 'mapped_line'):
            value = new.get(key)
            if isinstance(value, int) and value > boundary:
                value -= len(added)
            if old.get(key) != value:
                raise VerificationError('non-target normalized line changed')
    result = {'units': len(spec['units']), 'unique_unit_pairs': len(expected), 'projection_pairs': len(ap),
              'appended_pairs': len(added), 'protected_baseline_tokens': len(bt) - len(indices)}
    if 'replace' in spec:
        result['replaced_pairs'] = len(indices)
    return result


def verify(baseline, payload, manifest, gdre, probe):
    baseline, payload, manifest = map(Path, (baseline, payload, manifest))
    raw, spec = read_manifest(manifest)
    if script_localize.sha_file(baseline) != spec['baseline_sha256'] or script_localize.sha_file(payload) != spec['payload_sha256']:
        raise VerificationError('PCK binding mismatch')
    script_localize.check_tools(Path(gdre).resolve(), Path(probe).resolve())
    blobs = []
    for path, key in ((baseline, 'baseline_entry_sha256'), (payload, 'payload_entry_sha256')):
        try:
            data = gdc_payload_verify._entry_bytes(path, funeral.inspect_pck(path), spec['entry'])
        except gdc_payload_verify.VerificationError as exc:
            raise VerificationError(str(exc)) from exc
        if sha(data) != spec[key]:
            raise VerificationError('PCK entry binding mismatch')
        blobs.append(data)
    with tempfile.TemporaryDirectory(prefix='projection-payload-') as temp:
        work = Path(temp)
        for name, blob in zip(('original', 'candidate'), blobs):
            (work / (name + '.gdc')).write_bytes(blob)
        out = script_localize.inspect(work, Path(gdre).resolve(), Path(probe).resolve(), ['original', 'candidate'])
        before, after = [script_localize.split_payload(out[name][1], out[name][0]) for name in ('original', 'candidate')]
        result = compare(before, after, spec)
    if script_localize.sha_file(baseline) != spec['baseline_sha256'] or script_localize.sha_file(payload) != spec['payload_sha256'] or manifest.read_bytes() != raw:
        raise VerificationError('input changed during verification')
    script_localize.check_tools(Path(gdre).resolve(), Path(probe).resolve())
    return {'status': 'selected_projection_passed', 'manifest_sha256': sha(raw), **result,
            'limitations': ['compares protected tokens to the specified baseline, not the original game', 'unit-to-source assignments are manifest inputs', 'game behavior, other resources and complete protected fields are not verified']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'payload', 'manifest', 'gdre-dir', 'token-probe'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.baseline, args.payload, args.manifest, args.gdre_dir, args.token_probe)
    except (OSError, ValueError, KeyError, TypeError, IndexError, script_localize.LocalizeError) as exc:
        parser.exit(1, 'PROJECTION_VERIFY_FAILED: ' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
