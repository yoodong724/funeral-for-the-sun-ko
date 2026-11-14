#!/usr/bin/env python3
"""Verify explicitly approved PackedScene text-only edits in two PCKs.

A policy is trusted to describe authorized display fields and translations.
An entry without such a policy is unsupported, never implicitly approved.
This checks serialized bytes, not runtime visibility or game semantics.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from project.adapters import funeral, rsrc_inspect, scene_node_localize


class VerificationError(ValueError):
    """A supported policy or payload was violated."""


class UnsupportedScene(ValueError):
    """This serialized scene or change policy is not supported."""


class ManifestError(ValueError):
    """The scope or a verification input is invalid."""


def _u32(value):
    if value.tag != 3 or len(value.raw) != 8:
        raise UnsupportedScene('unsupported bundle integer')
    return struct.unpack_from('<i', value.raw, 4)[0]


def _packed(value, tag):
    if value.tag != tag:
        raise UnsupportedScene('unsupported packed array type')
    reader = rsrc_inspect._Reader(value.raw)
    if reader.u32() != tag:
        raise UnsupportedScene('invalid packed array tag')
    count = reader.u32()
    if tag == 34:
        result = [reader.string() for _ in range(count)]
    else:
        if count > (len(value.raw) - reader.pos) // 4:
            raise UnsupportedScene('invalid packed array count')
        result = [struct.unpack('<i', reader.take(4))[0] for _ in range(count)]
    if reader.pos != len(value.raw):
        raise UnsupportedScene('packed array trailing data')
    return result


def _bundle(data):
    try:
        doc = rsrc_inspect._parse(data)
        root = doc.resources[-1]
        kind = rsrc_inspect._Reader(root.kind_raw)
        if kind.string() != 'PackedScene' or kind.pos != len(kind.data):
            raise UnsupportedScene('not a PackedScene root')
        props = [p.value for p in root.properties if p.name == '_bundled']
        if len(props) != 1 or props[0].tag != 26:
            raise UnsupportedScene('unsupported scene bundle')
        children = props[0].children
        if len(children) % 2:
            raise UnsupportedScene('invalid bundle dictionary')
        items = {}
        positions = {}
        for i in range(0, len(children), 2):
            (ks, key), (vs, value) = children[i:i + 2]
            if ks != ('dict_key', i//2) or vs != ('dict_value', i//2) or key.tag != 5 or not isinstance(key.text, str) or key.text in items:
                raise UnsupportedScene('invalid bundle dictionary key')
            items[key.text] = value
            positions[key.text] = i//2
        required = {'names','variants','node_count','nodes','conn_count','conns','node_paths','version'}
        if not required <= items.keys() or _u32(items['version']) != 3:
            raise UnsupportedScene('unsupported scene bundle version')
        names = _packed(items['names'],34)
        words = _packed(items['nodes'],32)
        conns = _packed(items['conns'],32)
        variants = items['variants']
        paths = items['node_paths']
        if variants.tag != 30 or paths.tag != 30:
            raise UnsupportedScene('unsupported scene arrays')
        vals = [value for _, value in variants.children]
        if [step for step,_ in variants.children] != [('array',i) for i in range(len(vals))]:
            raise UnsupportedScene('invalid variant sequence')
        # NodePath component names are indexed in the RSRC string table, not
        # the PackedScene bundle's separate node-name table.
        table_reader=rsrc_inspect._Reader(doc.strings)
        resource_names=tuple(table_reader.string() for _ in range(table_reader.u32()))
        if table_reader.pos!=len(doc.strings):raise UnsupportedScene('invalid resource string table')
        if [step for step,_ in paths.children] != [('array',i) for i in range(len(paths.children))]:
            raise UnsupportedScene('invalid node path sequence')
        path_parts=[]
        for _, value in paths.children:
            if value.tag!=22:raise UnsupportedScene('unsupported node path variant')
            reader=rsrc_inspect._Reader(value.raw);reader.names=resource_names
            if reader.u32()!=22:raise UnsupportedScene('invalid node path encoding')
            count_names=reader.u16();subnames=reader.u16()
            if not count_names or subnames:raise UnsupportedScene('absolute or subname node path unsupported')
            parts=[reader.name() for _ in range(count_names)]
            if reader.pos!=len(value.raw) or any(not name or name in ('.','..') or any(c in name for c in '/:\\') or any(ord(c)<32 or ord(c) in (127,65533) for c in name) for name in parts):
                raise UnsupportedScene('noncanonical parent node path')
            path_parts.append(parts)
        types = [4 if value.tag == 5 else 100+value.tag for value in vals]
        strings = [value.text if value.tag == 5 else None for value in vals]
        count = _u32(items['node_count'])
        if count < 1:
            raise UnsupportedScene('invalid scene node count')
        raw_nodes=[]; cursor=0
        for index in range(count):
            if cursor+6>len(words):raise UnsupportedScene('truncated scene nodes')
            parent,owner,kind,name_word,instance,nprops=words[cursor:cursor+6];cursor+=6
            name_index=name_word&((1<<18)-1)
            if name_index>=len(names) or nprops<0 or cursor+nprops*2>=len(words):
                raise UnsupportedScene('invalid node record')
            node_name=names[name_index]
            if not node_name or any(ch in node_name for ch in '/:\\') or any(ord(ch)<32 or ord(ch) in (127,65533) for ch in node_name):
                raise UnsupportedScene('unsupported node name')
            props=[]
            for _ in range(nprops):
                word,vid=words[cursor:cursor+2];cursor+=2
                ni=word&((1<<30)-1)
                if ni>=len(names) or vid<0 or vid>=len(vals):raise UnsupportedScene('invalid node property')
                props.append({'name':names[ni],'type':types[vid],'string':strings[vid]})
            ngroups=words[cursor];cursor+=1
            if ngroups<0 or cursor+ngroups>len(words):raise UnsupportedScene('invalid node groups')
            cursor+=ngroups
            raw_nodes.append({'index':index,'parent':parent,'owner':owner,'instance':instance,'name':node_name,'properties':props})
        if cursor!=len(words):raise UnsupportedScene('unread node records')
        def node_path(index):
            seen=set();components=[]
            while True:
                if index in seen or not 0<=index<len(raw_nodes):raise UnsupportedScene('invalid node parent')
                seen.add(index);node=raw_nodes[index];parent=node['parent']
                if parent in (-1,0x7fffffff):
                    if index!=0:raise UnsupportedScene('ambiguous root parent')
                    break
                if parent<0 or parent&~((1<<30)|scene_node_localize.FLAG_MASK):raise UnsupportedScene('invalid parent flags')
                components.append(node['name'])
                if parent&(1<<30):
                    reference=parent&scene_node_localize.FLAG_MASK
                    if reference>=len(path_parts):raise UnsupportedScene('parent node path index out of range')
                    return '/'.join(path_parts[reference]+list(reversed(components)))
                index=parent&scene_node_localize.FLAG_MASK
            return '/'.join(reversed(components)) or '.'
        state=[{'index':x['index'],'path':node_path(x['index']),'properties':x['properties']} for x in raw_nodes]
        if len({x['path'] for x in state})!=len(state):raise UnsupportedScene('ambiguous node paths')
        if raw_nodes[0]['parent'] not in (-1,0x7fffffff) or raw_nodes[0]['owner']!=-1:
            raise UnsupportedScene('invalid scene root ownership')
        node_by_path={x['path']:x['index'] for x in state}
        for index,node in enumerate(raw_nodes):
            owner=node['owner']
            if owner!=-1:
                if owner<0 or owner&~scene_node_localize.FLAG_MASK or owner>=len(state) or owner==index:
                    raise UnsupportedScene('ambiguous node owner')
                owner_path=state[owner]['path'];current_path=state[index]['path']
                if owner_path!='.' and not current_path.startswith(owner_path+'/'):
                    raise UnsupportedScene('node owner is not an ancestor')
            parent=node['parent']
            if parent>=0 and parent!=0x7fffffff and parent&(1<<30):
                parent_path='/'.join(path_parts[parent&scene_node_localize.FLAG_MASK])
                if parent_path not in node_by_path:
                    # The path may traverse inside an instanced scene, but at
                    # least one explicit ancestor must be that instance.
                    anchored=any(n['instance']>=0 and state[i]['path']!='.' and parent_path.startswith(state[i]['path']+'/') for i,n in enumerate(raw_nodes))
                    if not anchored:raise UnsupportedScene('unanchored parent node path')
        base=_u32(items['base_scene']) if 'base_scene' in items else -1
        scene={'bundle_version':3,'names':names,'variant_strings':strings,'variant_types':types,
               'state_nodes':state,'node_count':count,'nodes':words,'connections':conns,
               'node_paths_count':len(paths.children),'connection_count':_u32(items['conn_count']),'base_scene':base}
        return doc,root.identity,positions['variants'],vals,scene
    except UnsupportedScene:
        raise
    except (rsrc_inspect.RsrcError,IndexError,KeyError,TypeError,ValueError,struct.error) as exc:
        raise UnsupportedScene('unsupported serialized scene: '+str(exc)) from exc


def _changes(changes):
    if not isinstance(changes,list) or not changes:
        raise ManifestError('text policy requires changes')
    seen=set()
    for c in changes:
        if not isinstance(c,dict) or set(c)!={'node_path','property','original','replacement'}:
            raise ManifestError('invalid display change')
        try:path=scene_node_localize.node_path(c['node_path'])
        except scene_node_localize.SceneNodeError as exc:raise ManifestError(str(exc)) from exc
        if c['property'] not in ('text','tooltip_text','placeholder_text'):
            raise ManifestError('only display properties are supported')
        if not isinstance(c['original'],str) or not isinstance(c['replacement'],str) or c['original']==c['replacement']:
            raise ManifestError('invalid approved text')
        key=(path,c['property'])
        if key in seen:raise ManifestError('duplicate approved location')
        seen.add(key)


def verify_scene(original,candidate,changes):
    """Check exact approved node strings and every other serialized byte."""
    _changes(changes)
    _,root,key,variants,scene=_bundle(original)
    try:
        edits=scene_node_localize.analyze_bundle(scene,changes)
    except scene_node_localize.SceneNodeError as exc:
        raise VerificationError('invalid or shared approved use: '+str(exc)) from exc
    allowed=[]
    for edit in edits:
        v=variants[edit['variant_index']]
        if v.tag!=5 or v.text!=edit['original']:
            raise VerificationError('source variant mismatch')
        allowed.append(rsrc_inspect.StringChange(root,'_bundled',(('dict_value',key),('array',edit['variant_index'])),edit['original'],edit['replacement']))
    try:
        rsrc_inspect.compare_rsrc(original,candidate,changes=allowed)
    except rsrc_inspect.RsrcError as exc:
        raise VerificationError('unapproved serialized difference: '+str(exc)) from exc
    return {'status':'passed','locations':len(changes),'variants':len(allowed)}


_DISPLAY_STRING_PROPERTIES = frozenset(('text', 'tooltip_text', 'placeholder_text'))
# Names alone cannot establish semantics: even a custom property called
# resource_path could be displayed. A caller must also supply an explicitly
# evidenced location; every other custom property remains unclassified.
_PROTECTED_STRING_PROPERTIES = frozenset(('node_path', 'resource_path', 'unique_id'))


def _shared_string_uses(bundle, variants, protected_locations=frozenset()):
    try:
        scene_node_localize.analyze_bundle(bundle, [])
    except scene_node_localize.SceneNodeError as exc:
        raise UnsupportedScene('shared-string use graph unsupported: '+str(exc)) from exc
    uses={}; locations={}; anchors={}; words=bundle['nodes']; position=0
    for node in bundle['state_nodes']:
        parent,owner,kind,name,instance,count=words[position:position+6];position+=6
        anchors[node['path']]=(parent,owner,kind,name,instance)
        if instance>=0:uses.setdefault(instance&scene_node_localize.FLAG_MASK,[]).append(('unknown','instance',node['path']))
        for prop in node['properties']:
            name_word,index=words[position:position+2];position+=2
            key=(node['path'],prop['name']);locations[key]=index
            if name_word&(1<<30):role='unknown'
            elif prop['name'] in _DISPLAY_STRING_PROPERTIES:role='display'
            elif prop['name'] in _PROTECTED_STRING_PROPERTIES and key in protected_locations:role='protected'
            else:role='unknown'
            uses.setdefault(index,[]).append((role,'property',key))
        groups=words[position];position+=1+groups
    position=0;conns=bundle['connections']
    for i in range(bundle['connection_count']):
        count=conns[position+5];position+=6
        for index in conns[position:position+count]:uses.setdefault(index,[]).append(('unknown','connection',i))
        position+=count+1
    if bundle['base_scene']>=0:uses.setdefault(bundle['base_scene'],[]).append(('unknown','base_scene',0))
    shared={i:u for i,u in uses.items() if variants[i].tag==5 and len(u)>1 and any(x[0]=='display' for x in u)}
    return shared,locations,anchors


def verify_shared_strings(original,candidate, *, protected_locations=frozenset()):
    """Check proven non-display uses of shared strings; never authorize text.

    A preserved value is only a partial result. Unknown use or unmatched scene
    identity remains unsupported; this is not whole-scene verification.
    """
    try:
        _,_,_,before_values,before=_bundle(original)
        _,_,_,after_values,after=_bundle(candidate)
        old,_,old_anchors=_shared_string_uses(before,before_values,protected_locations)
        _,new_locations,new_anchors=_shared_string_uses(after,after_values)
        if not old:raise UnsupportedScene('no shared display String use established')
        if after['names'][:len(before['names'])]!=before['names']:
            raise UnsupportedScene('scene name table changed; node identity not established')
        checked=unknown=0
        for index,uses in old.items():
            for role,kind,key in uses:
                if role=='unknown':unknown+=1;continue
                if role!='protected':continue
                path,_=key
                if old_anchors.get(path)!=new_anchors.get(path) or key not in new_locations:
                    raise UnsupportedScene('protected shared-use location cannot be matched')
                value=after_values[new_locations[key]]
                if value.tag!=5:
                    raise UnsupportedScene('protected shared-use type changed')
                if value.text!=before_values[index].text:
                    raise VerificationError('non-display shared String changed')
                checked+=1
        return {'status':'unsupported','s2_scope':'shared_string_non_display_uses_only',
                'shared_variants':len(old),'protected_uses_preserved':checked,
                'unknown_uses':unknown,'reason':'공유 위치 승인 및 전체 장면 보호 미결속'}
    except VerificationError as exc:return {'status':'failed','reason':str(exc)}
    except (UnsupportedScene,IndexError,KeyError,TypeError,ValueError) as exc:
        return {'status':'unsupported','reason':str(exc)}


def _entry(pack,index,name):
    if name not in index.entries:raise VerificationError('missing entry: '+name)
    e=index.entries[name]
    if e.size>scene_node_localize.MAX_SCENE_BYTES:raise UnsupportedScene('scene exceeds supported size')
    with pack.open('rb') as f:f.seek(e.offset);data=f.read(e.size)
    if len(data)!=e.size or hashlib.md5(data).digest()!=e.md5:raise VerificationError('entry integrity mismatch: '+name)
    return data


def _entry_digest(pack,index,name):
    """Check PCK entry integrity without imposing the scene parser size limit."""
    if name not in index.entries:raise VerificationError('missing entry: '+name)
    e=index.entries[name];md5=hashlib.md5();sha=hashlib.sha256();remaining=e.size
    with pack.open('rb') as f:
        f.seek(e.offset)
        while remaining:
            data=f.read(min(1024*1024,remaining))
            if not data:raise VerificationError('truncated entry: '+name)
            remaining-=len(data);md5.update(data);sha.update(data)
    if md5.digest()!=e.md5:raise VerificationError('entry integrity mismatch: '+name)
    return sha.digest()


def _parse_manifest(path):
    try:spec=json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=scene_node_localize.object_pairs)
    except (OSError,UnicodeError,json.JSONDecodeError,scene_node_localize.SceneNodeError) as exc:raise ManifestError('invalid manifest') from exc
    if not isinstance(spec,dict) or set(spec)!={'format','source_sha256','payload_sha256','entries'} or spec['format']!='funeral-full-scene-map-v1':raise ManifestError('unsupported manifest')
    for k in ('source_sha256','payload_sha256'):
        if not isinstance(spec[k],str) or not re.fullmatch('[0-9a-f]{64}',spec[k]):raise ManifestError('invalid PCK binding')
    if not isinstance(spec['entries'],list) or not spec['entries']:raise ManifestError('empty scene scope')
    seen=set()
    for x in spec['entries']:
        if not isinstance(x,dict) or set(x)!={'entry','policy','reason'} or not funeral._canonical_relative_path(x['entry']) or not x['entry'].endswith('.scn') or x['entry'] in seen or not isinstance(x['reason'],str):raise ManifestError('invalid scene entry')
        seen.add(x['entry'])
        if x['policy'] is not None:
            if not isinstance(x['policy'],dict) or set(x['policy'])!={'format','changes'} or x['policy']['format']!='node-string-v1':raise ManifestError('unsupported policy format')
            _changes(x['policy']['changes'])
        elif not x['reason']:
            raise ManifestError('unsupported scene needs a reason')
    return spec


def verify_payload(original,payload,manifest, *, s2_protected_locations=None):
    """Return one result per changed .scn; unsupported remains incomplete."""
    spec=_parse_manifest(manifest);original=Path(original);payload=Path(payload)
    try:
        if scene_node_localize.sha_file(original)!=spec['source_sha256'] or scene_node_localize.sha_file(payload)!=spec['payload_sha256']:
            raise ManifestError('PCK binding mismatch')
        oi,pi=funeral.inspect_pck(original),funeral.inspect_pck(payload)
        old={n for n in oi.entries if n.endswith('.scn')};new={n for n in pi.entries if n.endswith('.scn')}
        if old!=new:raise ManifestError('added or removed scene outside replacement scope')
        actual=set()
        for name in old:
            # Byte-level coverage cannot silently skip a scene due to policy.
            if _entry_digest(original,oi,name)!=_entry_digest(payload,pi,name):actual.add(name)
        if actual!={x['entry'] for x in spec['entries']}:
            raise ManifestError('manifest does not cover exactly the changed scenes')
        results=[]
        for x in spec['entries']:
            name=x['entry']
            if x['policy'] is None:
                if 'shared variant has non-target use' in x['reason']:
                    locations = (s2_protected_locations or {}).get(name, frozenset())
                    try:outcome=verify_shared_strings(_entry(original,oi,name),_entry(payload,pi,name),protected_locations=locations)
                    except UnsupportedScene as exc:outcome={'status':'unsupported','reason':str(exc)}
                    except VerificationError as exc:outcome={'status':'failed','reason':str(exc)}
                    if outcome['status']=='failed':
                        results.append({'entry':name,**outcome});continue
                    results.append({'entry':name,'status':'unsupported','reason':x['reason'],'s2':outcome});continue
                if 'external resource table or order changed' in x['reason']:
                    from project.adapters import scene_font_s1
                    try:outcome=scene_font_s1.verify_font_additions(_entry(original,oi,name),_entry(payload,pi,name))
                    except UnsupportedScene as exc:outcome={'status':'unsupported','reason':str(exc)}
                    except VerificationError as exc:outcome={'status':'failed','reason':str(exc)}
                    if outcome['status']=='failed':
                        results.append({'entry':name,**outcome});continue
                    results.append({'entry':name,'status':'unsupported','reason':x['reason'],'s1':outcome});continue
                results.append({'entry':name,'status':'unsupported','reason':x['reason']});continue
            try:
                out=verify_scene(_entry(original,oi,name),_entry(payload,pi,name),x['policy']['changes'])
                results.append({'entry':name,**out})
            except UnsupportedScene as exc:results.append({'entry':name,'status':'unsupported','reason':str(exc)})
            except VerificationError as exc:results.append({'entry':name,'status':'failed','reason':str(exc)})
        counts={k:sum(x['status']==k for x in results) for k in ('passed','failed','unsupported')}
        if scene_node_localize.sha_file(original)!=spec['source_sha256'] or scene_node_localize.sha_file(payload)!=spec['payload_sha256']:
            raise ManifestError('PCK changed during verification')
        return {'status':'failed' if counts['failed'] else ('incomplete' if counts['unsupported'] else 'passed'),
                'scope':'changed_scenes_serialized_structure_only','counts':counts,'entries':results}
    except (OSError,funeral.PckError) as exc:
        raise ManifestError('PCK read failed: '+str(exc)) from exc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',required=True);parser.add_argument('--payload',required=True);parser.add_argument('--manifest',required=True);parser.add_argument('--report',required=True)
    args=parser.parse_args();out=Path(args.report)
    try:
        if out.exists() or out.is_symlink():raise ManifestError('report path already exists')
        result=verify_payload(args.original,args.payload,args.manifest)
        with out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
        print('SCENE_VERIFY',result['status'],json.dumps(result['counts']))
        if result['status']=='failed':return 1
        if result['status']=='incomplete':return 3
        return 0
    except (ManifestError,VerificationError,UnsupportedScene,OSError,ValueError) as exc:
        print('SCENE_VERIFY_INPUT_ERROR:',str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
