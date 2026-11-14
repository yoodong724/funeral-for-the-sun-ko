"""Recompute fixed scene-batch approvals; unbound scenes remain unsupported.

The pinned snapshot is the trust anchor. Scope is derived from the recorded
072 scene manifest, but its text policies are never authorization inputs.
"""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from scripts import parallel_translations as parallel
from l10n_primitives.core import revision
from project.adapters import full_scene_verify as scene, funeral, scene_font_s1

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path('scratch/technical/t3-scene-ledger-072/approval-snapshot.json')
SNAPSHOT_SHA256 = '922548bcd8a739bf41a3ee8f005ea405e7d3bf4eca790ab1e7799f4f73f19c87'
SOURCE = '17131a6f209694a81c56645a278f371c3dcce53e5ce9369ddb0dfc3867f1215c'
PAYLOAD = '23b4b9c3f32a79057fcb5725f76796abb53e0e1be81a53f42af85e919716b56f'
CATALOG = 'project/catalog/scene-candidates-26591563/catalog.json'
LOCATIONS = 'project/context/scene-candidates-26591563/locations.local.jsonl'
SCOPE = 'scratch/technical/t3-full-scene-072/nodepath-encoding/manifest-expanded.local.json'

class LedgerError(ValueError):
    pass

def _sha(data):
    return hashlib.sha256(data).hexdigest()

def _load_snapshot(root):
    data=(root/SNAPSHOT).read_bytes()
    if _sha(data)!=SNAPSHOT_SHA256: raise LedgerError('고정 승인 스냅샷 불일치')
    obj=json.loads(data)
    if obj.get('format')!='funeral-scene-approval-snapshot-v1': raise LedgerError('승인 스냅샷 형식 불일치')
    return obj

def _checked(root,snapshot,path):
    path=str(path)
    if path not in snapshot['files']: raise LedgerError('승인 스냅샷 밖의 자료')
    data=(root/path).read_bytes()
    if _sha(data)!=snapshot['files'][path]: raise LedgerError('승인 자료가 변경됨: '+path)
    return data

def _context(root,snapshot):
    catalog=json.loads(_checked(root,snapshot,CATALOG))
    units={u['id']:u for u in catalog['units']}
    if len(units)!=len(catalog['units']):raise LedgerError('catalog ID 중복')
    locations=defaultdict(list)
    for line in _checked(root,snapshot,LOCATIONS).splitlines():
        loc=json.loads(line);locations[loc['unit_id']].append(loc)
    return catalog,units,locations

def build_ledger(root=ROOT, diagnostics=None):
    root=Path(root); snapshot=_load_snapshot(root)
    try:
        catalog,units,locations=_context(root,snapshot)
        coordinate_ids=defaultdict(set)
        for uid, records in locations.items():
            for loc in records:
                coordinate_ids[(loc.get('physical'),loc.get('node_path'),loc.get('property'))].add(uid)
        selected={};conflicts=set()
        for batch in snapshot['batches']:
            try:
                prefix=Path(batch['directory']); names=['catalog.json','plan.json',batch['report'],batch['merged']]
                plan=json.loads(_checked(root,snapshot,prefix/'plan.json'))
                names += [t['translations'] for t in plan['tasks']]
                for n in names:_checked(root,snapshot,prefix/n)
                for name in snapshot['files']:
                    if name.startswith('project/canonical/c002/'):_checked(root,snapshot,name)
                if prefix.name=='t5-b358-001':_checked(root,snapshot,'scratch/batches/t5-b358-review-001.ko.md')
                inputs=parallel.load_inputs(root/prefix/'catalog.json',root/'project/canonical/c002',root/prefix/'plan.json')
                report=json.loads(_checked(root,snapshot,prefix/batch['report']))
                merged=json.loads(_checked(root,snapshot,prefix/batch['merged']))
                if (not report.get('ok') or not report.get('passed') or not report.get('merged_output_written')
                    or report.get('source_revision')!=inputs.catalog['source_revision']
                    or report.get('canonical_revision')!=inputs.canonical_revision
                    or report.get('plan_revision')!=revision(inputs.plan)
                    or report.get('merged_translations_revision')!=revision(merged)):
                    raise LedgerError('병합 revision 또는 상태 불일치')
                values=[]
                for task in inputs.plan['tasks']:
                    status,value,code=parallel.inspect_task(inputs,task)
                    if code or not status['passed'] or value is None:raise LedgerError('배치 검사 실패')
                    values.append(value)
                if parallel.merged_translations(inputs,values)!=merged:raise LedgerError('병합 결과 불일치')
                batch_units={u['id']:u for u in inputs.catalog['units']}
                batch_selected={}
                for tr in merged['translations']:
                    uid=tr['id']; options=locations.get(uid,[])
                    if uid not in units or uid not in batch_units or len(options)!=1:raise LedgerError('catalog 위치 1:1 불일치')
                    u=units[uid]; bu=batch_units[uid]; loc=options[0]
                    if (u['source']!=bu['source'] or u['source_hash']!=bu['source_hash']
                        or tr['source_hash']!=u['source_hash'] or loc['source_hash']!=u['source_hash']
                        or loc['source_revision']!=catalog['source_revision']
                        or loc['property'] not in ('text','tooltip_text','placeholder_text')
                        or not isinstance(loc['physical'],str) or not isinstance(loc['node_path'],str)
                        or not isinstance(tr['target'],str) or not tr['target']):
                        raise LedgerError('문안·위치 결속 불일치')
                    key=(loc['physical'],loc['node_path'],loc['property'])
                    if coordinate_ids[key] != {uid}:raise LedgerError('장면 좌표 1:1 불일치')
                    val={'node_path':key[1],'property':key[2],'original':u['source'],'replacement':tr['target']}
                    if key in batch_selected:raise LedgerError('배치 좌표 중복')
                    batch_selected[key]=val
                for n in names:_checked(root,snapshot,prefix/n)
                for key,val in batch_selected.items():
                    if key in selected and selected[key]!=val:conflicts.add(key)
                    else:selected[key]=val
            except (LedgerError,OSError,ValueError,KeyError,TypeError,AttributeError,parallel.ToolError) as exc:
                if diagnostics is not None:diagnostics[str(prefix)]=str(exc)
        for key in conflicts:selected.pop(key,None)
        _checked(root,snapshot,CATALOG);_checked(root,snapshot,LOCATIONS);_load_snapshot(root)
        return selected
    except (OSError,ValueError,KeyError,TypeError,AttributeError,parallel.ToolError) as exc:
        raise LedgerError('장면 원장 작성 실패: '+str(exc)) from exc

def verify(original,payload,root=ROOT):
    root=Path(root); snapshot=_load_snapshot(root); diagnostics={}; ledger=build_ledger(root,diagnostics)
    scope=json.loads(_checked(root,snapshot,SCOPE)); original=Path(original); payload=Path(payload)
    if scene.scene_node_localize.sha_file(original)!=SOURCE or scene.scene_node_localize.sha_file(payload)!=PAYLOAD:
        raise LedgerError('원본 또는 후보 PCK 해시 불일치')
    old=funeral.inspect_pck(original); new=funeral.inspect_pck(payload)
    from project.adapters import scene_legacy_ledger
    try:
        legacy=scene_legacy_ledger.resolve_records(root,original,old,diagnostics)
        for key,value in legacy.items():
            if key in ledger:
                ledger.pop(key)
                diagnostics['legacy_conflict:'+str(key)]='승인 좌표가 충돌함'
            else:
                ledger[key]=value
    except (scene_legacy_ledger.EvidenceError,OSError,ValueError,KeyError,TypeError,
            scene.UnsupportedScene,scene.VerificationError) as exc:
        diagnostics['legacy']=str(exc)
    text_only=[r for r in scope['entries'] if r['policy'] is not None]
    fonts=[r for r in scope['entries'] if 'external resource table or order changed' in r['reason']]
    if len(text_only)!=8 or len(fonts)!=89:raise LedgerError('S1 및 기존 통과 장면 범위 불일치')
    results=[]
    for row in text_only+fonts:
        name=row['entry']; changes=[val for (entry,_,_),val in sorted(ledger.items()) if entry==name]
        if not changes and row not in fonts:
            results.append({'entry':name,'status':'unsupported','reason':'승인 위치 자동 1:1 결속 없음'});continue
        try:
            a=scene._entry(original,old,name);b=scene._entry(payload,new,name)
            if row in fonts:
                font=scene_font_s1.verify_font_additions(a,b)
                if font.get('s1_structure')!='passed':
                    results.append({'entry':name,'status':font['status'],'reason':font.get('reason','S1 미지원')});continue
                if not changes:
                    results.append({'entry':name,'status':'unsupported','reason':'S1 구조 확인; 승인 위치 자동 1:1 결속 없음'});continue
                permitted={(change['node_path'], prop) for change in changes for prop in scene_font_s1.FONT_PROPERTIES}
                bound=scene_font_s1.verify_font_additions(a,b,approved_nodes=permitted)
                if bound['status']!='passed':
                    results.append({'entry':name,'status':'unsupported','reason':'S1 구조 확인; 추가 글꼴 사용 노드 승인 결속 불가'});continue
                from project.adapters import scene_font_exact
                exact=scene_font_exact.verify(a,b,changes)
                scene_legacy_ledger.check_spacing_config(root,name,exact.get('spacing_paths',[]))
                results.append({'entry':name,'status':exact['status'],
                                'reason':'승인 배치·글꼴 사용 및 나머지 직렬화 구조 검증',
                                'locations':len(changes)});continue
            checked=scene.verify_scene(a,b,changes)
            results.append({'entry':name,'status':checked['status'],'reason':'승인 배치·위치와 전체 직렬화 대조', 'locations':len(changes)})
        except (scene.UnsupportedScene,scene.ManifestError,scene.VerificationError,scene_legacy_ledger.EvidenceError,OSError) as exc:
            # A partial ledger cannot distinguish missing approvals from an
            # unapproved protected change, so never call this a proven failure.
            results.append({'entry':name,'status':'unsupported','reason':'승인 범위 또는 전체 구조 미확정: '+str(exc)})
    if scene.scene_node_localize.sha_file(original)!=SOURCE or scene.scene_node_localize.sha_file(payload)!=PAYLOAD:
        raise LedgerError('PCK가 검사 중 변경됨')
    counts=dict(Counter(x['status'] for x in results))
    return {'status':'unsupported' if counts.get('unsupported') else 'passed','counts':counts,
            'entries':results,'unapproved_batches':diagnostics,
            'scope':'승인 배치 scene-candidates 1:1 및 S1 부분 구조; 승인 스냅샷은 고정 신뢰 근거'}
