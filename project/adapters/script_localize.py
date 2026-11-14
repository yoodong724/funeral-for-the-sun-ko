#!/usr/bin/env python3
"""Localize explicit display literals in a supported Godot 4.4.1 GDSC.

This narrow adapter recompiles GDScript source; it never patches GDC bytes.
It publishes only after the pinned native tokenizer and serialized pool checks
have confirmed that every non-target byte and token stays within the contract.
"""

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tokenize


GDRE_HASHES = {
    'gdre_tools.x86_64': 'b6f75a4509af3f23f963b6d8533b6c4627714fd786d1dfc343649bac135f670b',
    'gdre_tools.pck': '427130033c0795abc01f6f114497844763ba108a9363eb396b3f01e650b1e641',
    'libGodotMonoDecompNativeAOT.so': '7b1f00efe8f4d5adfb6bbcc60c169ec7ba6bf0392917524c7c9dc6830af2e6c6',
}
PROBE_SHA256 = 'e63a1030a7e37eaa3bd0240ecb27bffdd23b61c600e69e1fbf7755060dc2bb1e'
MAX_PAYLOAD = 64 * 1024 * 1024

# LocalTokenInspection is the pinned diagnostic build of the unchanged Godot
# 4.4.1 tokenizer. It exposes the native token array, maps and Variant values.
PROBE_SCRIPT = r'''extends SceneTree
func _initialize() -> void:
    var probe = ClassDB.instantiate("LocalTokenInspection")
    if probe == null:
        printerr("PROBE_UNAVAILABLE")
        quit(2)
        return
    for name in OS.get_cmdline_user_args():
        var path := "/work/" + name + ".gdc"
        var data := FileAccess.get_file_as_bytes(path)
        if data.size() < 12:
            printerr("PROBE_BAD_HEADER")
            quit(2)
            return
        var size := data.decode_u32(8)
        var payload := data.slice(12).decompress(size, FileAccess.COMPRESSION_ZSTD)
        if payload.size() != size:
            printerr("PROBE_DECOMPRESSION_FAILED")
            quit(2)
            return
        var bytes_file := FileAccess.open("/work/" + name + ".payload", FileAccess.WRITE)
        if bytes_file == null:
            quit(2)
            return
        bytes_file.store_buffer(payload)
        bytes_file.close()
        var result: Dictionary = probe.inspect_buffer(path)
        if result.get("error", -1) != OK:
            printerr("PROBE_DECODE_FAILED")
            quit(2)
            return
        result["input_sha256"] = FileAccess.get_sha256(path)
        for row in result.tokens:
            row["literal_bytes"] = var_to_bytes(row.literal).hex_encode()
            row["literal"] = str(row.literal)
        var out := FileAccess.open("/work/" + name + ".json", FileAccess.WRITE)
        if out == null:
            quit(2)
            return
        out.store_string(JSON.stringify(result))
        out.close()
    quit(0)
'''


class LocalizeError(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def object_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise LocalizeError('duplicate JSON key')
        result[key] = value
    return result


def validate_plan(plan, restored):
    keys = {'format', 'source_sha256', 'changes'}
    if restored:
        keys.add('restored_sha256')
    if not isinstance(plan, dict) or set(plan) != keys or plan['format'] != 'gdscript-display-v1':
        raise LocalizeError('unsupported request format')
    for key in ('source_sha256', 'restored_sha256') if restored else ('source_sha256',):
        if not isinstance(plan[key], str) or not re.fullmatch('[0-9a-f]{64}', plan[key]):
            raise LocalizeError('invalid hash')
    if not isinstance(plan['changes'], list) or not plan['changes']:
        raise LocalizeError('empty changes')
    indices, positions = set(), set()
    for change in plan['changes']:
        if not isinstance(change, dict) or set(change) != {'token_index', 'line', 'column', 'original', 'replacement'}:
            raise LocalizeError('invalid change')
        for key in ('token_index', 'line', 'column'):
            if type(change[key]) is not int or change[key] < (0 if key == 'token_index' else 1):
                raise LocalizeError('invalid location')
        if not isinstance(change['original'], str) or not isinstance(change['replacement'], str):
            raise LocalizeError('invalid string')
        if change['original'] == change['replacement']:
            raise LocalizeError('unchanged replacement')
        position = (change['line'], change['column'])
        if change['token_index'] in indices or position in positions:
            raise LocalizeError('duplicate location')
        indices.add(change['token_index'])
        positions.add(position)


def validate_gdc(data):
    if len(data) < 12 or len(data) > MAX_PAYLOAD or data[:4] != b'GDSC':
        raise LocalizeError('unsupported GDC header')
    version, size = struct.unpack_from('<II', data, 4)
    if version != 100 or not 0 < size <= MAX_PAYLOAD:
        raise LocalizeError('unsupported GDC version or compression')


def check_tools(gdre, probe):
    if not shutil.which('bwrap'):
        raise LocalizeError('bwrap is required')
    for name, digest in GDRE_HASHES.items():
        if not (gdre / name).is_file() or sha_file(gdre / name) != digest:
            raise LocalizeError('unsupported GDRE tool hash')
    if not probe.is_file() or sha_file(probe) != PROBE_SHA256:
        raise LocalizeError('unsupported tokenizer probe hash')


def run_isolated(work, gdre, probe, executable, args, phase):
    command = [shutil.which('bwrap'), '--unshare-all', '--uid', '0', '--gid', '0', '--die-with-parent',
               '--clearenv', '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
               '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64', '--ro-bind', '/etc', '/etc',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/private',
               '--ro-bind', str(gdre), '/gdre', '--ro-bind', str(probe), '/engine/godot',
               '--bind', str(work), '/work', '--ro-bind', str(work / 'original.gdc'), '/work/original.gdc',
               '--setenv', 'HOME', '/private', '--setenv', 'XDG_DATA_HOME', '/private/data',
               '--setenv', 'XDG_CONFIG_HOME', '/private/config', '--setenv', 'XDG_CACHE_HOME', '/private/cache',
               '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'PATH', '/usr/bin:/bin',
               '--chdir', '/gdre' if executable == '/gdre/gdre_tools.x86_64' else '/work', executable, *args]
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=50)
    except subprocess.TimeoutExpired as exc:
        raise LocalizeError(phase + ' timed out') from exc
    if process.returncode or 'ERROR:' in process.stdout or 'WARNING:' in process.stdout:
        raise LocalizeError(phase + ' failed or logged an error/warning')


def compile_source(work, gdre, probe, name, directory):
    run_isolated(work, gdre, probe, '/gdre/gdre_tools.x86_64',
                 ['--headless', '--compile=/work/' + name + '.gd', '--bytecode=77af6ca',
                  '--output=/work/' + directory], 'compile')
    output = work / directory / (name + '.gdc')
    if not output.is_file():
        raise LocalizeError('compile output missing')
    data = output.read_bytes()
    validate_gdc(data)
    return data


def inspect(work, gdre, probe, names):
    project = work / 'probe-project'
    project.mkdir(exist_ok=True)
    (project / 'project.godot').write_text('config_version=5\n[application]\nconfig/name="TokenInspection"\n')
    (project / 'dump.gd').write_text(PROBE_SCRIPT)
    run_isolated(work, gdre, probe, '/engine/godot',
                 ['--headless', '--path', '/work/probe-project', '--script', 'res://dump.gd', '--', *names],
                 'tokenizer')
    result = {}
    for name in names:
        raw = (work / (name + '.gdc')).read_bytes()
        decoded = json.loads((work / (name + '.json')).read_text())
        payload = (work / (name + '.payload')).read_bytes()
        if decoded.get('error') != 0 or decoded.get('input_sha256') != sha(raw):
            raise LocalizeError('tokenizer source hash mismatch')
        if len(payload) != struct.unpack_from('<I', raw, 8)[0]:
            raise LocalizeError('unsupported decompressed size')
        result[name] = (decoded, payload)
    return result


def split_payload(payload, decoded):
    if len(payload) < 20:
        raise LocalizeError('unsupported payload')
    ids, constants, lines, unused, count = struct.unpack_from('<IIIII', payload)
    tokens = decoded.get('tokens')
    if unused or not isinstance(tokens, list) or count != len(tokens):
        raise LocalizeError('unsupported token header')
    position = 20
    for _ in range(ids):
        if position + 4 > len(payload):
            raise LocalizeError('unsupported identifier table')
        length = struct.unpack_from('<I', payload, position)[0]
        position += 4 + 4 * length
        if position > len(payload):
            raise LocalizeError('unsupported identifier table')
    token_start = len(payload) - 8 * count
    map_start = token_start - 16 * lines
    if not 20 <= position <= map_start <= token_start <= len(payload):
        raise LocalizeError('unsupported payload layout')
    words = []
    values = {}
    previous_line = 0
    for index, token in enumerate(tokens):
        word, line = struct.unpack_from('<II', payload, token_start + 8 * index)
        if (not word & 0x80 or word & 0x7f != token['type'] or line != token['start_line'] or
                token['index'] != index or line < 1 or line < previous_line):
            raise LocalizeError('unsupported token encoding')
        previous_line = line
        words.append(word)
        if token['type'] in (0, 3):
            constant = word >> 8
            encoded = bytes.fromhex(token['literal_bytes'])
            if constant in values and values[constant] != encoded:
                raise LocalizeError('inconsistent constant')
            values[constant] = encoded
    if set(values) != set(range(constants)):
        raise LocalizeError('unsupported unused or missing constants')
    if b''.join(values[i] for i in range(constants)) != payload[position:map_start]:
        raise LocalizeError('unsupported constant serialization')
    if decoded.get('line_map_size') != lines or decoded.get('column_map_size') != lines:
        raise LocalizeError('unsupported line map')
    return {'ids': payload[20:position], 'maps': payload[map_start:token_start],
            'token_bytes': payload[token_start:], 'words': words, 'values': values, 'tokens': tokens}


def selected_source(source, layout, changes):
    try:
        lexical = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise LocalizeError('unsupported source syntax') from exc
    selected = {c['token_index']: c for c in changes}
    if any(i >= len(layout['tokens']) for i in selected):
        raise LocalizeError('location out of bounds')
    replacements = []
    for line in {c['line'] for c in changes}:
        strings = [t for t in lexical if t.type == tokenize.STRING and t.start[0] == line]
        native = [t for t in layout['tokens'] if t['type'] == 3 and t['start_line'] == line
                  and t['literal_type'] in (4, 21, 22)]
        if len(strings) != len(native) or any(t['literal_type'] != 4 for t in native):
            raise LocalizeError('unsupported string location')
        for token, entry in zip(strings, native):
            try:
                value = ast.literal_eval(token.string)
            except (SyntaxError, ValueError) as exc:
                raise LocalizeError('unsupported string literal') from exc
            if token.start[0] != token.end[0] or value != entry['literal']:
                raise LocalizeError('unsupported string location')
            change = selected.get(entry['index'])
            if change is None:
                continue
            if change['line'] != line or token.start[1] + 1 != change['column'] or value != change['original']:
                raise LocalizeError('source location or original mismatch')
            replacements.append((token.start, token.end, json.dumps(change['replacement'], ensure_ascii=False)))
    if len(replacements) != len(changes):
        raise LocalizeError('source location or original mismatch')
    for index, change in selected.items():
        token = layout['tokens'][index]
        if token['type'] != 3 or token['literal_type'] != 4 or token['literal'] != change['original']:
            raise LocalizeError('source location or original mismatch')
        constant = layout['words'][index] >> 8
        refs = {i for i, word in enumerate(layout['words']) if word & 0x7f in (0, 3) and word >> 8 == constant}
        if not refs.issubset(selected) or len({selected[i]['replacement'] for i in refs}) != 1:
            raise LocalizeError('shared constant has unselected or divergent uses')
        if any(t['type'] == 3 and t['literal_type'] == 4 and i not in selected and t['literal'] == change['replacement']
               for i, t in enumerate(layout['tokens'])):
            raise LocalizeError('shared replacement collides with protected string')
    targets = {}
    for index, change in selected.items():
        target = change['replacement']
        constant = layout['words'][index] >> 8
        if target in targets and targets[target] != constant:
            raise LocalizeError('shared replacement merges distinct constants')
        targets[target] = constant
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(replacements, reverse=True):
        row = start[0] - 1
        lines[row] = lines[row][:start[1]] + replacement + lines[row][end[1]:]
    return ''.join(lines)


def compare_candidate(before, after, changes):
    if any(before[k] != after[k] for k in ('ids', 'maps', 'token_bytes')):
        raise LocalizeError('non-target raw token, identifier or map changed')
    if len(before['tokens']) != len(after['tokens']):
        raise LocalizeError('token count changed')
    if set(before['values']) != set(after['values']):
        raise LocalizeError('constant pool indices changed')
    allowed = {c['token_index']: c for c in changes}
    for i, (old, new) in enumerate(zip(before['tokens'], after['tokens'])):
        for key in ('index', 'type', 'literal_type', 'start_line', 'mapped_line', 'mapped_column'):
            if old.get(key) != new.get(key):
                raise LocalizeError('non-target token or map changed')
        if i in allowed:
            if old['literal'] != allowed[i]['original'] or new['literal'] != allowed[i]['replacement']:
                raise LocalizeError('target token mismatch')
        elif old['literal_bytes'] != new['literal_bytes']:
            raise LocalizeError('non-target constant changed')
    chosen = {before['words'][i] >> 8 for i in allowed}
    different = {i for i in before['values'] if before['values'][i] != after['values'][i]}
    if different != chosen:
        raise LocalizeError('non-target constant pool changed')
    return len(chosen)


def check_output_parent(output):
    parent = Path(output.anchor)
    for part in output.parent.parts[1:]:
        if part == '..':
            raise LocalizeError('unsupported output parent')
        parent /= part
        if parent.is_symlink() or not parent.is_dir():
            raise LocalizeError('unsupported output parent')


def apply(args):
    source, plan_path = Path(args.source).resolve(), Path(args.plan).resolve()
    gdre, probe = Path(args.gdre_dir).resolve(), Path(args.token_probe).resolve()
    output = Path(args.out_dir).absolute()
    check_output_parent(output)
    if output.exists() or output.is_symlink():
        raise LocalizeError('output directory must be new and its parent must exist')
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes.decode('utf-8'), object_pairs_hook=object_pairs)
    validate_plan(plan, bool(args.restored_source))
    if source.stat().st_size > MAX_PAYLOAD:
        raise LocalizeError('unsupported GDC file size')
    data = source.read_bytes()
    if sha(data) != plan['source_sha256']:
        raise LocalizeError('source hash mismatch')
    validate_gdc(data)
    check_tools(gdre, probe)
    with tempfile.TemporaryDirectory(prefix='gdscript-display-') as temp:
        work = Path(temp)
        (work / 'original.gdc').write_bytes(data)
        run_isolated(work, gdre, probe, '/gdre/gdre_tools.x86_64',
                     ['--headless', '--decompile=/work/original.gdc', '--bytecode=77af6ca',
                      '--output=/work/decompiled'], 'decompile')
        restored = work / 'decompiled/original.gd'
        if not restored.is_file():
            raise LocalizeError('decompile output missing')
        decompiled_sha256 = sha_file(restored)
        if args.restored_source:
            supplied = Path(args.restored_source).read_bytes()
            if sha(supplied) != plan['restored_sha256']:
                raise LocalizeError('restored source hash mismatch')
            restored.write_bytes(supplied)
        baseline = restored.read_text(encoding='utf-8')
        (work / 'baseline.gd').write_text(baseline, encoding='utf-8')
        noop = compile_source(work, gdre, probe, 'baseline', 'noop')
        if (work / 'baseline.gd').read_text(encoding='utf-8') != baseline:
            raise LocalizeError('restored source changed during compile')
        (work / 'noop.gdc').write_bytes(noop)
        native = inspect(work, gdre, probe, ['original', 'noop'])
        if native['original'][1] != native['noop'][1]:
            raise LocalizeError('no-op payload mismatch')
        decoded, payload = native['original']
        original_layout = split_payload(payload, decoded)
        localized = selected_source(baseline, original_layout, plan['changes'])
        (work / 'candidate.gd').write_text(localized, encoding='utf-8')
        candidate = compile_source(work, gdre, probe, 'candidate', 'compiled')
        if (work / 'candidate.gd').read_text(encoding='utf-8') != localized:
            raise LocalizeError('candidate source changed during compile')
        (work / 'candidate.gdc').write_bytes(candidate)
        candidate_probe = inspect(work, gdre, probe, ['candidate'])['candidate']
        candidate_layout = split_payload(candidate_probe[1], candidate_probe[0])
        count = compare_candidate(original_layout, candidate_layout, plan['changes'])
        if sha_file(source) != plan['source_sha256'] or sha_file(plan_path) != sha(plan_bytes):
            raise LocalizeError('source or request hash changed during processing')
        if args.restored_source and sha_file(Path(args.restored_source)) != plan['restored_sha256']:
            raise LocalizeError('restored source hash changed during processing')
        check_tools(gdre, probe)
        report = {'format': 'gdscript-display-result-v1', 'source_sha256': sha(data),
                  'request_sha256': sha(plan_bytes), 'decompiled_source_sha256': decompiled_sha256,
                  'baseline_source_sha256': sha(baseline.encode('utf-8')),
                  'source_payload_sha256': sha(payload), 'candidate_payload_sha256': sha(candidate_probe[1]),
                  'candidate_sha256': sha(candidate), 'selected_occurrences': len(plan['changes']),
                  'selected_token_indices': sorted(c['token_index'] for c in plan['changes']),
                  'changed_constants': count, 'non_target_token_bytes_changed': 0,
                  'non_target_constant_bytes_changed': 0, 'line_column_map_bytes_changed': 0,
                  'gdre_files_sha256': GDRE_HASHES, 'token_probe_sha256': PROBE_SHA256,
                  'limitations': 'Display classification, game behavior, font and installation are not verified.'}
        check_output_parent(output)
        output.mkdir()
        with (output / 'verification.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(report, indent=2) + '\n')
        with (output / 'localized.gdc').open('xb') as stream:
            stream.write(candidate)
    print('SCRIPT_LOCALIZE_OK:', report['candidate_sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest='command', required=True)
    command = subcommands.add_parser('apply')
    for name in ('source', 'plan', 'gdre-dir', 'token-probe', 'out-dir'):
        command.add_argument('--' + name, required=True)
    command.add_argument('--restored-source')
    args = parser.parse_args()
    try:
        apply(args)
    except (LocalizeError, OSError, ValueError, KeyError, TypeError, struct.error) as exc:
        print('SCRIPT_LOCALIZE_FAILED:', str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
