#!/usr/bin/env python3
"""Create one verified PackedScene node-String candidate from a pinned PCK."""
import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
WORKER = ROOT / 'scene_node_localize.gd'
INSPECTOR_SHA256 = '7ead99c82e425e95305cbe3f2e66187a8cb31875d16b4bd96650fdc5e29a1848'
PCK_READER_SHA256 = '0f15759099bf341210b5d86a930535ca9d331b7a09950ac10da475b56b94acb1'
SAVER_SHA256 = 'bba839ed5c1c115850db991d242b760b0eaa700ae864d1e51c729d08531de917'
OFFICIAL_SHA256 = '54215149d52efb1d653a3dec39d0993587bdf5daa2c56e787b5ee88417fb1339'
FLAG_MASK = (1 << 24) - 1
PROPERTY_NAME_MASK = (1 << 30) - 1
MAX_SCENE_BYTES = 64 * 1024 * 1024


class SceneNodeError(Exception):
    pass


def sha_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_module(name, path, expected):
    if sha_file(path) != expected:
        raise SceneNodeError('verification module hash mismatch')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def object_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise SceneNodeError('duplicate JSON key')
        result[key] = value
    return result


def resource_path(path):
    if not isinstance(path, str) or not path.startswith('res://'):
        raise SceneNodeError('invalid resource path')
    rest = path[6:]
    if (not rest or '\\' in rest or ':' in rest or any(ord(c) < 32 or ord(c) in (127, 65533) for c in rest)
            or any(part in ('', '.', '..') for part in rest.split('/'))):
        raise SceneNodeError('invalid resource path')
    return rest


def node_path(path):
    if not isinstance(path, str):
        raise SceneNodeError('invalid node location')
    value = path.removeprefix('./')
    if value == '.':
        return value
    if (not value or '\\' in value or ':' in value or any(ord(c) < 32 or ord(c) in (127, 65533) for c in value)
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise SceneNodeError('invalid node location')
    return value


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {'format', 'pack_sha256', 'logical_path', 'binary_path', 'source_sha256', 'changes'}:
        raise SceneNodeError('unsupported request format')
    if plan['format'] != 'scene-node-localize-v1':
        raise SceneNodeError('unsupported request format')
    for key in ('pack_sha256', 'source_sha256'):
        if not isinstance(plan[key], str) or not re.fullmatch('[0-9a-f]{64}', plan[key]):
            raise SceneNodeError('invalid hash')
    logical = resource_path(plan['logical_path'])
    binary = resource_path(plan['binary_path'])
    if not binary.endswith('.scn') or not (logical.endswith('.tscn') or logical == binary):
        raise SceneNodeError('unsupported scene path')
    if not isinstance(plan['changes'], list) or not plan['changes']:
        raise SceneNodeError('empty changes')
    seen = set()
    for change in plan['changes']:
        if not isinstance(change, dict) or set(change) != {'node_path', 'property', 'original', 'replacement'}:
            raise SceneNodeError('invalid change')
        path = node_path(change['node_path'])
        prop = change['property']
        if (not isinstance(prop, str) or not prop or any(ord(c) < 32 or ord(c) in (127, 65533) for c in prop)
                or not isinstance(change['original'], str) or not isinstance(change['replacement'], str)
                or change['original'] == change['replacement']):
            raise SceneNodeError('invalid change')
        key = (path, prop)
        if key in seen:
            raise SceneNodeError('duplicate location')
        seen.add(key)


def analyze_bundle(scene, changes):
    """Account for every version-3 pool reference before selecting values."""
    if not isinstance(scene, dict) or scene.get('bundle_version') != 3:
        raise SceneNodeError('unsupported bundle version')
    names, values = scene.get('names'), scene.get('variant_strings')
    types, state = scene.get('variant_types'), scene.get('state_nodes')
    nodes, conns = scene.get('nodes'), scene.get('connections')
    if any(not isinstance(x, list) for x in (names, values, types, state, nodes, conns)):
        raise SceneNodeError('invalid bundle shape')
    if len(values) != len(types) or len(state) != scene.get('node_count'):
        raise SceneNodeError('invalid bundle counts')
    node_paths_count = scene.get('node_paths_count')
    if type(node_paths_count) is not int or node_paths_count < 0:
        raise SceneNodeError('invalid node path count')
    if any(not isinstance(x, str) for x in names) or any(type(x) is not int for x in types + nodes + conns):
        raise SceneNodeError('invalid bundle values')
    uses, properties = defaultdict(list), {}
    position = 0
    try:
        for index, node in enumerate(state):
            if node['index'] != index or not isinstance(node['properties'], list):
                raise SceneNodeError('invalid state node')
            if position + 6 > len(nodes):
                raise SceneNodeError('truncated nodes')
            instance, count = nodes[position + 4], nodes[position + 5]
            position += 6
            if count < 0 or count != len(node['properties']) or position + count * 2 >= len(nodes):
                raise SceneNodeError('invalid property count')
            if instance >= 0:
                if instance & ~(FLAG_MASK | (1 << 30)):
                    raise SceneNodeError('unsupported instance flags')
                reference = instance & FLAG_MASK
                if reference >= len(values):
                    raise SceneNodeError('invalid instance reference')
                uses[reference].append(('instance', index))
            elif instance != -1:
                raise SceneNodeError('unsupported instance reference')
            path = node_path(node['path'])
            for prop in node['properties']:
                name_word = nodes[position]
                if name_word < 0 or name_word & ~(PROPERTY_NAME_MASK | (1 << 30)):
                    raise SceneNodeError('unsupported property flags')
                name_index = name_word & PROPERTY_NAME_MASK
                value_index = nodes[position + 1]
                position += 2
                if name_index >= len(names) or value_index < 0 or value_index >= len(values):
                    raise SceneNodeError('invalid property reference')
                if names[name_index] != prop['name'] or types[value_index] != prop['type']:
                    raise SceneNodeError('inconsistent property identity')
                if prop['type'] == 4 and (not isinstance(values[value_index], str) or values[value_index] != prop['string']):
                    raise SceneNodeError('inconsistent property value')
                key = (path, prop['name'])
                if key in properties:
                    raise SceneNodeError('duplicate node property')
                properties[key] = (value_index, bool(name_word & (1 << 30)))
                uses[value_index].append(('property', key))
            groups = nodes[position]
            position += 1
            if groups < 0 or position + groups > len(nodes):
                raise SceneNodeError('invalid groups')
            if any(group < 0 or group >= len(names) for group in nodes[position:position + groups]):
                raise SceneNodeError('invalid group reference')
            position += groups
        if position != len(nodes):
            raise SceneNodeError('unread node data')
        position = 0
        count = scene.get('connection_count')
        if type(count) is not int or count < 0:
            raise SceneNodeError('invalid connection count')
        for connection in range(count):
            if position + 6 > len(conns):
                raise SceneNodeError('truncated connection')
            for endpoint in conns[position:position + 2]:
                if endpoint < 0 or endpoint & ~(FLAG_MASK | (1 << 30)):
                    raise SceneNodeError('invalid connection node reference')
                limit = node_paths_count if endpoint & (1 << 30) else len(state)
                if (endpoint & FLAG_MASK) >= limit:
                    raise SceneNodeError('invalid connection node reference')
            signal, method, bind_count = conns[position + 2], conns[position + 3], conns[position + 5]
            position += 6
            if signal < 0 or signal >= len(names) or method < 0 or method >= len(names):
                raise SceneNodeError('invalid connection name')
            if bind_count < 0 or position + bind_count >= len(conns):
                raise SceneNodeError('invalid bind count')
            for bind in range(bind_count):
                reference = conns[position]
                position += 1
                if reference < 0 or reference >= len(values):
                    raise SceneNodeError('invalid bind reference')
                uses[reference].append(('connection_bind', (connection, bind)))
            if conns[position] < 0:
                raise SceneNodeError('invalid unbind count')
            position += 1
        if position != len(conns):
            raise SceneNodeError('unread connection data')
        base = scene.get('base_scene')
        if type(base) is not int or base < -1 or base >= len(values):
            raise SceneNodeError('invalid base scene')
        if base >= 0:
            uses[base].append(('base_scene', base))
    except (IndexError, KeyError, TypeError) as exc:
        raise SceneNodeError('invalid bundle data') from exc
    selected = {}
    for change in changes:
        key = (node_path(change['node_path']), change['property'])
        if key in selected or key not in properties:
            raise SceneNodeError('duplicate or missing node location')
        reference, deferred_node = properties[key]
        if deferred_node:
            raise SceneNodeError('unsupported node-reference property')
        if types[reference] != 4 or values[reference] != change['original']:
            raise SceneNodeError('stale node value or type')
        selected[key] = change
    grouped = defaultdict(list)
    for key, change in selected.items():
        grouped[properties[key][0]].append(change)
    edits = []
    for reference, group in sorted(grouped.items()):
        if any(kind != 'property' or key not in selected for kind, key in uses[reference]):
            raise SceneNodeError('shared variant has non-target use')
        targets = {change['replacement'] for change in group}
        if len(targets) != 1:
            raise SceneNodeError('shared variant has conflicting targets')
        edits.append({'variant_index': reference, 'original': group[0]['original'], 'replacement': group[0]['replacement'],
                      'locations': [{'node_path': node_path(item['node_path']), 'property': item['property']} for item in group]})
    if len(selected) != len(changes):
        raise SceneNodeError('incomplete node locations')
    return edits


def project_hashes(project):
    if project.is_symlink() or not project.is_dir():
        raise SceneNodeError('invalid project directory')
    paths = sorted(project.iterdir())
    if not (project / 'project.godot').is_file() or any(p.is_symlink() or not p.is_file() or p.name not in ('project.godot', 'stub.gd') for p in paths):
        raise SceneNodeError('unsupported project contents')
    stub = project / 'stub.gd'
    if stub.exists() and stub.read_bytes() != b'extends Node\n':
        raise SceneNodeError('unsupported project stub')
    return {p.name: sha_file(p) for p in paths}


def check_output_parent(output):
    parent = Path(output.anchor)
    for part in output.parent.parts[1:]:
        if part == '..':
            raise SceneNodeError('unsupported output parent')
        parent /= part
        if parent.is_symlink() or not parent.is_dir():
            raise SceneNodeError('unsupported output parent')


def read_entry(stream, entry, limit):
    if entry.size > limit:
        raise SceneNodeError('unsupported PCK entry size')
    stream.seek(entry.offset)
    data = stream.read(entry.size)
    if len(data) != entry.size or hashlib.md5(data).digest() != entry.md5:
        raise SceneNodeError('PCK entry checksum mismatch')
    return data


def source_from_pack(pck, index, plan):
    logical, binary = resource_path(plan['logical_path']), resource_path(plan['binary_path'])
    if binary not in index.entries:
        raise SceneNodeError('missing source entry')
    with pck.open('rb') as stream:
        if logical != binary:
            remap = logical + '.remap'
            if logical in index.entries or remap not in index.entries:
                raise SceneNodeError('source path remap mismatch')
            text = read_entry(stream, index.entries[remap], 16 * 1024).decode('utf-8')
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            match = re.fullmatch(r'path\s*=\s*"([^"]*)"', lines[1]) if len(lines) == 2 else None
            if len(lines) != 2 or lines[0] != '[remap]' or not match:
                raise SceneNodeError('source path remap mismatch')
            # Godot can serialize an apostrophe as \' inside a double-quoted path.
            # No other escapes are accepted, and the decoded path must match exactly.
            remap_path = match.group(1).replace("\\'", "'")
            if '\\' in remap_path or remap_path != plan['binary_path']:
                raise SceneNodeError('source path remap mismatch')
        elif logical + '.remap' in index.entries:
            raise SceneNodeError('unsupported direct scene remap')
        data = read_entry(stream, index.entries[binary], MAX_SCENE_BYTES)
    if hashlib.sha256(data).hexdigest() != plan['source_sha256']:
        raise SceneNodeError('source hash mismatch')
    return data


def bundled_variants(inspector, original):
    document = inspector._parse(original)
    root = document.resources[-1]
    matches = [p for p in root.properties if p.name == '_bundled']
    if len(matches) != 1 or matches[0].value.tag != 26:
        raise SceneNodeError('unsupported serialized bundle')
    children = dict(matches[0].value.children)
    keys = [index for (kind, index), value in children.items() if kind == 'dict_key' and value.text == 'variants']
    if len(keys) != 1:
        raise SceneNodeError('ambiguous variants array')
    array = children.get(('dict_value', keys[0]))
    if array is None or array.tag != 30:
        raise SceneNodeError('unsupported variants array')
    return root.identity, keys[0], dict(array.children)


def run_engine(engine, project, pck, work, mode):
    command = [shutil.which('bwrap'), '--unshare-all', '--uid', '0', '--gid', '0', '--die-with-parent', '--clearenv',
               '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
               '--symlink', 'usr/lib', '/lib64', '--ro-bind', '/etc', '/etc', '--proc', '/proc', '--dev', '/dev',
               '--tmpfs', '/tmp', '--tmpfs', '/private', '--ro-bind', str(pck), '/source/original.pck',
               '--ro-bind', str(project), '/project', '--ro-bind', str(WORKER), '/tool/worker.gd',
               '--ro-bind', str(engine), '/engine/godot', '--bind', str(work), '/work',
               '--ro-bind', str(work / 'config.json'), '/work/config.json']
    if mode == 'reload':
        command += ['--ro-bind', str(work / 'candidate.scn'), '/work/candidate.scn']
    command += [
               '--setenv', 'HOME', '/private', '--setenv', 'XDG_DATA_HOME', '/private/data',
               '--setenv', 'XDG_CONFIG_HOME', '/private/config', '--setenv', 'XDG_CACHE_HOME', '/private/cache',
               '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8', '--chdir', '/project',
               '/engine/godot', '--headless', '--path', '/project', '--script', '/tool/worker.gd', '--', mode]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=50)
    except subprocess.TimeoutExpired as exc:
        raise SceneNodeError('engine timeout') from exc
    if result.returncode or 'ERROR:' in result.stdout or 'WARNING:' in result.stdout:
        raise SceneNodeError('engine ' + mode + ' failed or logged a diagnostic')


def apply(args):
    plan_path, pck = Path(args.plan).resolve(), Path(args.pck).resolve()
    project = Path(args.project_dir).absolute()
    saver, official = Path(args.save_engine).resolve(), Path(args.reload_engine).resolve()
    output = Path(args.out_dir).absolute()
    check_output_parent(output)
    if output.exists() or output.is_symlink():
        raise SceneNodeError('output directory must be new')
    if output.is_relative_to(project.resolve()):
        raise SceneNodeError('output cannot be inside the read-only project')
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes.decode('utf-8'), object_pairs_hook=object_pairs)
    validate_plan(plan)
    if not shutil.which('bwrap') or sha_file(saver) != SAVER_SHA256 or sha_file(official) != OFFICIAL_SHA256:
        raise SceneNodeError('unsupported engine or isolation tool')
    project_files = project_hashes(project)
    worker_hash = sha_file(WORKER)
    inspector = load_module('node_localize_inspector', ROOT / 'rsrc_inspect.py', INSPECTOR_SHA256)
    pck_reader = load_module('node_localize_pck_reader', ROOT / 'funeral.py', PCK_READER_SHA256)
    if sha_file(pck) != plan['pack_sha256']:
        raise SceneNodeError('pack hash mismatch')
    index = pck_reader.inspect_pck(pck)
    if index.engine != (4, 4, 1):
        raise SceneNodeError('unsupported PCK engine')
    original = source_from_pack(pck, index, plan)
    root_id, variant_key, raw_variants = bundled_variants(inspector, original)
    with tempfile.TemporaryDirectory(prefix='scene-node-localize-') as temporary:
        work = Path(temporary)
        config = dict(plan)
        config['root_id'] = root_id
        config_path = work / 'config.json'
        config_path.write_text(json.dumps(config, ensure_ascii=False))
        initial_config_hash = sha_file(config_path)
        run_engine(official, project, pck, work, 'inspect')
        if sha_file(config_path) != initial_config_hash:
            raise SceneNodeError('inspection config changed')
        dump = json.loads((work / 'inspection.json').read_text())
        scene = dump['scene']
        edits = analyze_bundle(scene, plan['changes'])
        if len(raw_variants) != len(scene['variant_types']):
            raise SceneNodeError('serialized variant count mismatch')
        changes = []
        for edit in edits:
            value = raw_variants.get(('array', edit['variant_index']))
            if value is None or value.tag != 5 or value.text != edit['original']:
                raise SceneNodeError('serialized variant mismatch')
            changes.append(inspector.StringChange(root_id, '_bundled',
                           (('dict_value', variant_key), ('array', edit['variant_index'])),
                           edit['original'], edit['replacement']))
        config['edits'] = edits
        config_path.write_text(json.dumps(config, ensure_ascii=False))
        config_hash = sha_file(config_path)
        run_engine(saver, project, pck, work, 'build')
        candidate_path = work / 'candidate.scn'
        if candidate_path.stat().st_size > MAX_SCENE_BYTES:
            raise SceneNodeError('unsupported candidate size')
        candidate = candidate_path.read_bytes()
        inspector.compare_rsrc(original, candidate, changes=changes)
        run_engine(official, project, pck, work, 'reload')
        if (sha_file(candidate_path) != hashlib.sha256(candidate).hexdigest() or sha_file(config_path) != config_hash
                or sha_file(pck) != plan['pack_sha256'] or sha_file(plan_path) != hashlib.sha256(plan_bytes).hexdigest()
                or project_hashes(project) != project_files or sha_file(WORKER) != worker_hash
                or sha_file(saver) != SAVER_SHA256 or sha_file(official) != OFFICIAL_SHA256
                or sha_file(ROOT / 'rsrc_inspect.py') != INSPECTOR_SHA256
                or sha_file(ROOT / 'funeral.py') != PCK_READER_SHA256):
            raise SceneNodeError('input or candidate changed during processing')
        report = {'format': 'scene-node-localize-result-v1', 'pack_sha256': plan['pack_sha256'],
                  'logical_path': plan['logical_path'], 'binary_path': plan['binary_path'],
                  'source_sha256': plan['source_sha256'], 'request_sha256': hashlib.sha256(plan_bytes).hexdigest(),
                  'candidate_sha256': hashlib.sha256(candidate).hexdigest(), 'selected_locations': len(plan['changes']),
                  'changed_variants': len(edits), 'root_id': root_id, 'project_files_sha256': project_files,
                  'locations': [{'variant_index': edit['variant_index'], 'nodes': edit['locations'],
                                 'source_string_sha256': hashlib.sha256(edit['original'].encode()).hexdigest(),
                                 'target_string_sha256': hashlib.sha256(edit['replacement'].encode()).hexdigest()}
                                for edit in edits],
                  'worker_sha256': worker_hash, 'inspector_sha256': INSPECTOR_SHA256,
                  'pck_reader_sha256': PCK_READER_SHA256, 'dependencies': len(dump['dependencies']),
                  'save_engine_sha256': SAVER_SHA256, 'reload_engine_sha256': OFFICIAL_SHA256,
                  'limitations': 'No game UI, font, player state, PCK integration or Windows validation.'}
        check_output_parent(output)
        output.mkdir()
        with (output / 'verification.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(report, indent=2) + '\n')
        with (output / 'localized.scn').open('xb') as stream:
            stream.write(candidate)
    print('SCENE_NODE_OK:', report['candidate_sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('apply')
    for name in ('pck', 'plan', 'project-dir', 'save-engine', 'reload-engine', 'out-dir'):
        command.add_argument('--' + name, required=True)
    try:
        apply(parser.parse_args())
    except (SceneNodeError, OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print('SCENE_NODE_FAILED:', str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
