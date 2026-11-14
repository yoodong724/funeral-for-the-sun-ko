#!/usr/bin/env python3
"""Verify selected GDScript display changes against GDC bytes in a final PCK.

The manifest is an input contract: it does not establish that a selected
literal is safe to translate or that unlisted resources are protected.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from project.adapters import funeral, script_localize


class VerificationError(ValueError):
    """The input contract or selected GDC comparison failed."""


class ManifestError(VerificationError):
    """The manifest itself is malformed or unsupported."""


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _entry_bytes(pack, index, entry):
    if entry not in index.entries:
        raise VerificationError('missing selected PCK entry: ' + entry)
    info = index.entries[entry]
    if info.size > script_localize.MAX_PAYLOAD:
        raise VerificationError('selected GDC is too large')
    with pack.open('rb') as stream:
        stream.seek(info.offset)
        data = stream.read(info.size)
    if len(data) != info.size or hashlib.md5(data).digest() != info.md5:
        raise VerificationError('selected PCK entry checksum mismatch: ' + entry)
    script_localize.validate_gdc(data)
    return data


def _intermediate(root, value):
    if not funeral._canonical_relative_path(value):
        raise ManifestError('noncanonical intermediate path')
    path = root
    for segment in value.split('/'):
        path = path / segment
        if path.is_symlink():
            raise ManifestError('symlink intermediate path')
    if not path.is_file() or path.stat().st_size > script_localize.MAX_PAYLOAD:
        raise ManifestError('missing or oversized intermediate')
    data = path.read_bytes()
    script_localize.validate_gdc(data)
    return data


def read_manifest(manifest_path):
    """Parse and validate the manifest without examining either PCK."""
    raw = Path(manifest_path).read_bytes()
    try:
        spec = json.loads(raw.decode('utf-8'), object_pairs_hook=script_localize.object_pairs)
    except script_localize.LocalizeError as exc:
        raise ManifestError(str(exc)) from exc
    if not isinstance(spec, dict) or set(spec) != {'format', 'source_sha256', 'payload_sha256', 'entries'} or spec['format'] != 'funeral-gdc-structural-map-v1':
        raise ManifestError('unsupported manifest format')
    if not all(_hash(spec[k]) for k in ('source_sha256', 'payload_sha256')):
        raise ManifestError('invalid PCK hash')
    if not isinstance(spec['entries'], list) or not spec['entries']:
        raise ManifestError('empty selected GDC list')
    seen = set()
    for entry in spec['entries']:
        if not isinstance(entry, dict) or set(entry) != {'entry', 'stages'}:
            raise ManifestError('unsupported entry format')
        name, stages = entry['entry'], entry['stages']
        if not funeral._canonical_relative_path(name) or not name.endswith('.gdc') or name in seen:
            raise ManifestError('invalid or duplicate selected GDC entry')
        seen.add(name)
        if not isinstance(stages, list) or len(stages) not in (1, 2):
            raise ManifestError('one or two stages required')
        for i, stage in enumerate(stages):
            keys = {'plan', 'candidate_sha256'} | ({'intermediate_file'} if i < len(stages) - 1 else set())
            if not isinstance(stage, dict) or set(stage) != keys or not _hash(stage['candidate_sha256']):
                raise ManifestError('unsupported stage format')
            if i < len(stages) - 1 and not funeral._canonical_relative_path(stage['intermediate_file']):
                raise ManifestError('noncanonical intermediate path')
            plan = stage['plan']
            if not isinstance(plan, dict):
                raise ManifestError('invalid stage plan')
            try:
                script_localize.validate_plan(plan, 'restored_sha256' in plan)
            except script_localize.LocalizeError as exc:
                raise ManifestError(str(exc)) from exc
    return raw, spec


def verify(original, payload, manifest_path, gdre, probe):
    original, payload, manifest_path = map(lambda p: Path(p).resolve(), (original, payload, manifest_path))
    gdre, probe = Path(gdre).resolve(), Path(probe).resolve()
    raw, spec = read_manifest(manifest_path)
    if script_localize.sha_file(original) != spec['source_sha256'] or script_localize.sha_file(payload) != spec['payload_sha256']:
        raise VerificationError('PCK hash mismatch')
    entries = spec['entries']
    script_localize.check_tools(gdre, probe)
    old_index, new_index = funeral.inspect_pck(original), funeral.inspect_pck(payload)
    checked = []
    for entry in entries:
        name, stages = entry['entry'], entry['stages']
        before = _entry_bytes(original, old_index, name)
        final = _entry_bytes(payload, new_index, name)
        blobs = [before]
        for i, stage in enumerate(stages):
            if stage['plan']['source_sha256'] != _digest(blobs[-1]):
                raise VerificationError('stage source hash mismatch')
            candidate = _intermediate(manifest_path.parent, stage['intermediate_file']) if i < len(stages) - 1 else final
            if _digest(candidate) != stage['candidate_sha256']:
                raise VerificationError('stage candidate hash mismatch')
            blobs.append(candidate)
        with tempfile.TemporaryDirectory(prefix='gdc-payload-verify-') as temp:
            work = Path(temp)
            names = ['original'] + [f'stage{i}' for i in range(1, len(blobs))]
            for label, data in zip(names, blobs):
                (work / (label + '.gdc')).write_bytes(data)
            decoded = script_localize.inspect(work, gdre, probe, names)
            layouts = [script_localize.split_payload(decoded[label][1], decoded[label][0]) for label in names]
            changes = 0
            for i, stage in enumerate(stages):
                selected = stage['plan']['changes']
                for change in selected:
                    idx = change['token_index']
                    if idx >= len(layouts[i]['tokens']):
                        raise VerificationError('selected token index outside source')
                    token = layouts[i]['tokens'][idx]
                    if token['type'] != 3 or token['literal_type'] != 4 or token['start_line'] != change['line']:
                        raise VerificationError('selected token type or source line mismatch')
                changes += script_localize.compare_candidate(layouts[i], layouts[i + 1], selected)
        checked.append({'entry': name, 'original_sha256': _digest(before), 'final_sha256': _digest(final),
                        'stages': len(stages), 'selected_occurrences': sum(len(s['plan']['changes']) for s in stages),
                        'changed_constants_across_stages': changes})
    if (script_localize.sha_file(original) != spec['source_sha256'] or
            script_localize.sha_file(payload) != spec['payload_sha256'] or manifest_path.read_bytes() != raw):
        raise VerificationError('input changed during verification')
    script_localize.check_tools(gdre, probe)
    return {'format': 'funeral-gdc-structural-result-v1', 'status': 'selected_scripts_passed',
            'manifest_sha256': _digest(raw), 'source_sha256': spec['source_sha256'],
            'payload_sha256': spec['payload_sha256'], 'entries': checked,
            'limitations': ['only selected scripts and authorized tokens checked',
                            'source column is not independently resolved from native token data',
                            'display classification, other resources, game state and release readiness not checked']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'payload', 'manifest', 'gdre-dir', 'token-probe'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        report = verify(args.original, args.payload, args.manifest, args.gdre_dir, args.token_probe)
    except (OSError, ValueError, KeyError, TypeError, IndexError, script_localize.LocalizeError) as exc:
        parser.exit(1, 'GDC_VERIFY_FAILED: ' + str(exc) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
