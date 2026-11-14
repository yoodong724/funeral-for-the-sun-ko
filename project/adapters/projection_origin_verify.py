#!/usr/bin/env python3
"""Bind an approved projection source delta to original and baseline PCK GDCs.

The approved helper source is a trusted input. This verifies byte reproducibility
and source scope, not the correctness of an approved translation or game state.
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


def source_parts(original, projected):
    prefix = 'extends Control\n'
    old_call = 'page_text.text = current_page.text'
    new_call = 'page_text.text = ko_flashback_display(current_page.text)'
    if not original.startswith(prefix) or not projected.startswith(prefix):
        raise VerificationError('source prefix mismatch')
    if original.count(old_call) != 1 or projected.count(new_call) != 1:
        raise VerificationError('display call count mismatch')
    restored = projected.replace(new_call, old_call)
    tail = original[len(prefix):]
    if not restored[len(prefix):].endswith(tail):
        raise VerificationError('non-display source changed')
    helper = restored[len(prefix):len(restored) - len(tail)]
    marker = 'const _KO_INTRO_DISPLAY_PAIRS = '
    end = '\n\nfunc ko_flashback_display'
    if helper.count(marker) != 1 or helper.count(end) != 1:
        raise VerificationError('projection helper shape mismatch')
    head, rest = helper.split(marker, 1)
    table, function = rest.split(end, 1)
    try:
        pairs = json.loads(table, object_pairs_hook=script_localize.object_pairs)
    except (json.JSONDecodeError, script_localize.LocalizeError) as exc:
        raise VerificationError('invalid projection source table') from exc
    if not isinstance(pairs, list) or not pairs or any(not isinstance(row, list) or len(row) != 2 or not all(isinstance(v, str) and v for v in row) for row in pairs):
        raise VerificationError('invalid projection pairs')
    if len({row[0] for row in pairs}) != len(pairs):
        raise VerificationError('duplicate projection source')
    return pairs, (head, function)


def verify(original_pck, baseline_pck, original_source, baseline_source, approved_intro, manifest, gdre, probe):
    paths = [Path(x).resolve() for x in (original_pck, baseline_pck, original_source, baseline_source, approved_intro, manifest)]
    original_pck, baseline_pck, original_source, baseline_source, approved_intro, manifest = paths
    raw = manifest.read_bytes()
    spec = json.loads(raw.decode('utf-8'), object_pairs_hook=script_localize.object_pairs)
    required = {'format', 'entry', 'original_pck_sha256', 'baseline_pck_sha256', 'original_gdc_sha256', 'baseline_gdc_sha256', 'original_source_sha256', 'baseline_source_sha256', 'approved_intro_sha256'}
    if not isinstance(spec, dict) or set(spec) != required or spec['format'] != 'funeral-projection-origin-v1':
        raise VerificationError('invalid origin manifest')
    if not funeral._canonical_relative_path(spec['entry']) or not spec['entry'].endswith('.gdc'):
        raise VerificationError('invalid GDC path')
    for key in required - {'format', 'entry'}:
        if not isinstance(spec[key], str) or not re.fullmatch(r'[0-9a-f]{64}', spec[key]):
            raise VerificationError('invalid digest')
    source_paths = [(original_source, 'original_source_sha256'), (baseline_source, 'baseline_source_sha256'), (approved_intro, 'approved_intro_sha256')]
    source_bytes = [path.read_bytes() for path, _ in source_paths]
    for data, (_, key) in zip(source_bytes, source_paths):
        if sha(data) != spec[key]:
            raise VerificationError('source binding mismatch')
    originals = [p.decode('utf-8') for p in source_bytes]
    intro_pairs, intro_helper = source_parts(originals[0], originals[2])
    baseline_pairs, baseline_helper = source_parts(originals[0], originals[1])
    if intro_helper != baseline_helper or baseline_pairs[:len(intro_pairs)] != intro_pairs:
        raise VerificationError('approved helper or intro projection changed')
    pairs = [(original_pck, 'original_pck_sha256', 'original_gdc_sha256'), (baseline_pck, 'baseline_pck_sha256', 'baseline_gdc_sha256')]
    blobs = []
    for path, pck_key, gdc_key in pairs:
        if script_localize.sha_file(path) != spec[pck_key]:
            raise VerificationError('PCK binding mismatch')
        try:
            data = gdc_payload_verify._entry_bytes(path, funeral.inspect_pck(path), spec['entry'])
        except gdc_payload_verify.VerificationError as exc:
            raise VerificationError(str(exc)) from exc
        if sha(data) != spec[gdc_key]:
            raise VerificationError('GDC binding mismatch')
        blobs.append(data)
    gdre, probe = Path(gdre).resolve(), Path(probe).resolve()
    script_localize.check_tools(gdre, probe)
    with tempfile.TemporaryDirectory(prefix='projection-origin-') as temp:
        work = Path(temp)
        (work/'original.gdc').write_bytes(blobs[0])
        for name, data in zip(('original', 'baseline'), source_bytes[:2]):
            (work/(name+'.gd')).write_bytes(data)
            (work/(name+'-out')).mkdir()
            compiled = script_localize.compile_source(work, gdre, probe, name, name+'-out')
            expected = blobs[0 if name == 'original' else 1]
            if compiled != expected:
                raise VerificationError(name + ' compiled bytes differ from actual PCK')
    for path, key in [(original_pck, 'original_pck_sha256'), (baseline_pck, 'baseline_pck_sha256'), *source_paths]:
        if script_localize.sha_file(path) != spec[key]:
            raise VerificationError('input changed during verification')
    if manifest.read_bytes() != raw:
        raise VerificationError('manifest changed during verification')
    script_localize.check_tools(gdre, probe)
    return {'status':'selected_origin_passed', 'manifest_sha256':sha(raw), 'intro_pairs':len(intro_pairs),
            'baseline_pairs':len(baseline_pairs), 'original_and_baseline_compiled_byte_equal':True,
            'unchanged_original_source_except_display_call_and_helper':True,
            'limitations':['approved helper source and its meaning are trusted inputs', 'compiler and source transformation do not prove all game behavior or saved data', 'other scripts, resources and complete protected fields are not checked']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('original-pck','baseline-pck','original-source','baseline-source','approved-intro','manifest','gdre-dir','token-probe'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    try:
        result=verify(args.original_pck,args.baseline_pck,args.original_source,args.baseline_source,args.approved_intro,args.manifest,args.gdre_dir,args.token_probe)
    except (OSError,ValueError,KeyError,TypeError,IndexError,script_localize.LocalizeError) as exc:
        parser.exit(1,'PROJECTION_ORIGIN_FAILED: '+str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
