"""Fail-closed S1 check of PackedScene external font additions.

This checks only the external resource table and uses of newly added resources.
It does not verify other scene changes or independently authorize node policies.
"""
import struct
from collections import defaultdict
from project.adapters import full_scene_verify as scene, rsrc_inspect, scene_node_localize

FONT_PATHS = frozenset('res://__korean_localization__/fonts/' + name for name in (
    'fallback.fontdata', 'noto_kr_variation.res', 'century_variation.res',
    'tutorial_button_variation.res', 'georgia_variation.res', 'b020_bold_kr.res',
    'b020_italic_kr.res', 'b020_java_kr.res', 'b020_regular_kr.res', 'tutorial_courier_kr.res'))
FONT_PROPERTIES = frozenset(('font', 'theme_override_fonts/font'))


def external_table(raw):
    reader = rsrc_inspect._Reader(raw)
    count = reader.u32()
    if count > (len(raw)-4)//16:
        raise scene.UnsupportedScene('invalid external table count')
    rows = []
    for _ in range(count):
        start = reader.pos
        kind, path, uid = reader.string(), reader.string(), reader.u64()
        rows.append((kind, path, uid, raw[start:reader.pos]))
    if reader.pos != len(raw):
        raise scene.UnsupportedScene('trailing external table bytes')
    return rows


def _references(value, path=()):
    if value.tag == 24:
        if len(value.raw) >= 12 and struct.unpack_from('<I', value.raw, 4)[0] == 3:
            yield path, struct.unpack_from('<I', value.raw, 8)[0]
    for step, child in value.children:
        yield from _references(child, path + (step,))


def font_uses(doc, root, variant_key, variants, bundle, first_new):
    """Account for every appended external reference and every bundle use."""
    refs = {}
    for resource in doc.resources:
        for prop in resource.properties:
            for path, ext_id in _references(prop.value):
                if ext_id < first_new:
                    continue
                if (resource.identity != root or prop.name != '_bundled' or len(path) != 2
                        or path[0] != ('dict_value', variant_key) or path[1][0] != 'array'):
                    raise scene.VerificationError('new external resource referenced outside direct scene variants')
                vi = path[1][1]
                if vi in refs or vi >= len(variants):
                    raise scene.VerificationError('invalid external variant reference')
                refs[vi] = ext_id
    try:
        scene_node_localize.analyze_bundle(bundle, [])
    except scene_node_localize.SceneNodeError as exc:
        raise scene.UnsupportedScene('scene references unsupported: ' + str(exc)) from exc
    uses = defaultdict(list)
    words = bundle['nodes']; pos = 0
    for node in bundle['state_nodes']:
        instance, count = words[pos+4], words[pos+5]; pos += 6
        if instance >= 0:
            uses[instance & scene_node_localize.FLAG_MASK].append(('instance', node['path']))
        for prop in node['properties']:
            name_word, index = words[pos:pos+2]; pos += 2
            uses[index].append(('property', node['path'], prop['name'], bool(name_word & (1 << 30))))
        groups = words[pos]; pos += 1 + groups
    conn = bundle['connections']; pos = 0
    for index in range(bundle['connection_count']):
        bind_count = conn[pos+5]; pos += 6
        for ref in conn[pos:pos+bind_count]:
            uses[ref].append(('connection', index))
        pos += bind_count + 1
    if bundle['base_scene'] >= 0:
        uses[bundle['base_scene']].append(('base',))
    found = []
    for vi, ext_id in refs.items():
        if not uses[vi]:
            raise scene.UnsupportedScene('new font variant has no observable use')
        for use in uses[vi]:
            if use[0] != 'property' or use[2] not in FONT_PROPERTIES or use[3]:
                raise scene.VerificationError('new external resource used outside font property')
            found.append((use[1], use[2], ext_id))
    return found


def verify_font_additions(original, candidate, approved_nodes=None):
    """Check S1; approved_nodes is {(node_path, property)} or None if unbound.

    The result never claims whole-scene protection or independent approval.
    """
    try:
        old = rsrc_inspect._parse(original)
        doc, root, key, variants, bundle = scene._bundle(candidate)
        before, after = external_table(old.external), external_table(doc.external)
        if len(after) < len(before) or after[:len(before)] != before:
            raise scene.VerificationError('original external resources changed order, identity or path')
        extra = after[len(before):]
        if not extra:
            raise scene.UnsupportedScene('no appended external fonts')
        for kind, path, uid, _ in extra:
            if path not in FONT_PATHS or kind not in ('FontFile','FontVariation'):
                raise scene.VerificationError('unapproved external resource added')
            if uid != 0xffffffffffffffff:
                raise scene.UnsupportedScene('appended external UID resolution is unverified')
        uses = font_uses(doc, root, key, variants, bundle, len(before))
        if {ext for _,_,ext in uses} != set(range(len(before),len(after))):
            raise scene.UnsupportedScene('new external resource has no direct font use')
        if approved_nodes is None:
            return {'status':'unsupported','s1_structure':'passed','reason':'글꼴 노드 승인 결속 미확인', 'fonts':len(extra),'uses':len(uses)}
        if any((path,prop) not in approved_nodes for path,prop,_ in uses):
            raise scene.VerificationError('new font used at a nonapproved node')
        return {'status':'passed','s1_structure':'passed','fonts':len(extra),'uses':len(uses)}
    except scene.VerificationError as exc:
        return {'status':'failed','reason':str(exc)}
    except (scene.UnsupportedScene,rsrc_inspect.RsrcError,ValueError,IndexError,TypeError,struct.error) as exc:
        return {'status':'unsupported','reason':str(exc)}
