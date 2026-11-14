"""승인된 기존 UI 배치와 장면 좌표를 고정 증거로 재계산한다."""
import hashlib
import json
from pathlib import Path
from scripts import parallel_translations as parallel
from l10n_primitives.core import revision
from project.adapters import full_scene_verify as scene, funeral

SNAPSHOT=Path('scratch/technical/t3-scene-residual-072/approval-snapshot.json')
SNAPSHOT_SHA='f5952344f364ca7620a31c892ae7e0f7ab32fead79dcef17f7b3bbe81d051554'
MAPPING='scratch/technical/vertical-build-001/mapping.json'
SPACING_CONFIGS={
 '.godot/exported/133200997/export-9a6472db00b05a25ee0fc211f5e650e9-town square.scn': ('res://Solanor/backgrounds/town square.tscn','scratch/technical/t5-b254-resource/font-project/config.json'),
 ".godot/exported/133200997/export-9e35c742bc2bc0788e4e49979ab75cbb-childrens'bedroomhall (2).scn": ("res://Solanor/childrens'bedroomhall (2).tscn",'scratch/technical/t5-b254-hall-font/font-project/config.json'),
}
BATCHES=(
 ('b001','project/catalog/b001-ui/catalog.json','scratch/batches/b001-ui/plan-001.json','scratch/batches/b001-ui/merge-report-001.json','scratch/batches/b001-ui/merged-001.json','project/canonical/c001','scratch/technical/vertical-ui/ui/project/config.local.json'),
 ('b002','project/catalog/b002-name-ui/catalog.json','scratch/batches/b002-name-ui/plan-001.json','scratch/batches/b002-name-ui/merge-report-001.json','scratch/batches/b002-name-ui/translations-merged-001.json','project/canonical/c001','scratch/technical/vertical-ui/name/project/config.local.json'),
 ('notes','scratch/technical/t5-notes-english/catalog.json','scratch/technical/t5-notes-english/translation-plan.json','scratch/technical/t5-notes-english/merge-reviewed.json','scratch/technical/t5-notes-english/merged-reviewed.json','project/canonical/c002','scratch/technical/t5-notes-english/locations.local.json'))

class EvidenceError(ValueError):pass

def _sha(data):return hashlib.sha256(data).hexdigest()
def _snapshot(root):
 raw=(root/SNAPSHOT).read_bytes()
 if _sha(raw)!=SNAPSHOT_SHA:raise EvidenceError('기존 UI 승인 스냅샷 불일치')
 obj=json.loads(raw)
 if obj.get('format')!='funeral-legacy-scene-approval-snapshot-v1':raise EvidenceError('스냅샷 형식 불일치')
 return obj

def _checked(root,snapshot,path):
 path=str(path)
 if path not in snapshot['files']:raise EvidenceError('승인 근거가 스냅샷 범위 밖임')
 data=(root/path).read_bytes()
 if _sha(data)!=snapshot['files'][path]:raise EvidenceError('승인 근거가 변경됨: '+path)
 return data

def check_spacing_config(root,entry,spacing_paths):
 """고정된 기술 설정이 존재하는 장면은 해당 다중행 노드와도 대조한다."""
 if entry not in SPACING_CONFIGS or not spacing_paths:return
 root=Path(root);snapshot=_snapshot(root);logical,path=SPACING_CONFIGS[entry]
 data=json.loads(_checked(root,snapshot,path))
 if data.get('logical')!=logical:raise EvidenceError('줄 간격 기술 설정의 장면 불일치')
 allowed={t['node_path'] for t in data['targets'] if t.get('multiline') is True}
 if not set(spacing_paths)<=allowed:raise EvidenceError('줄 간격 기술 설정의 노드 불일치')

def approved_records(root,diagnostics=None):
 """단위 ID·원문·위치·승인 번역을 대조하며 손상된 배치만 제외한다."""
 root=Path(root);snapshot=_snapshot(root);records=[]
 for name,catalog,plan,report,merged,canonical,location in BATCHES:
  try:
   paths=[catalog,plan,report,merged,location]
   plan_obj=json.loads(_checked(root,snapshot,plan))
   paths += [str(Path(plan).parent/t['translations']) for t in plan_obj['tasks']]
   paths += [p for p in snapshot['files'] if p.startswith(canonical+'/')]
   for p in paths:_checked(root,snapshot,p)
   inputs=parallel.load_inputs(root/catalog,root/canonical,root/plan)
   rep=json.loads(_checked(root,snapshot,report));result=json.loads(_checked(root,snapshot,merged))
   if (not rep.get('ok') or not rep.get('passed') or not rep.get('merged_output_written')
       or rep.get('source_revision')!=inputs.catalog['source_revision']
       or rep.get('canonical_revision')!=inputs.canonical_revision
       or rep.get('plan_revision')!=revision(inputs.plan)
       or rep.get('merged_translations_revision')!=revision(result)):
    raise EvidenceError('병합 revision 불일치')
   values=[]
   for task in inputs.plan['tasks']:
    checked,value,code=parallel.inspect_task(inputs,task)
    if code or not checked['passed'] or value is None:raise EvidenceError('작업 검사 실패')
    values.append(value)
   if parallel.merged_translations(inputs,values)!=result:raise EvidenceError('병합 재계산 불일치')
   units={x['id']:x for x in inputs.catalog['units']};translations={x['id']:x for x in result['translations']}
   loc=json.loads(_checked(root,snapshot,location));batch_records=[]
   if name=='notes':
    for r in loc:
     uid=r['unit_id']; u=units[uid]; t=translations[uid]
     if (r['source_hash']!=u['source_hash'] or t['source_hash']!=u['source_hash']
         or u['pointer']!='/nodes/'+r['key'] or r['property'] not in ('text','tooltip_text','placeholder_text')):
      raise EvidenceError('노트 위치 불일치')
     batch_records.append({'physical':r['physical'],'original_sha256':r['source_sha256'],
                           'node_path':r['node_path'],'property':r['property'],'original':u['source'],'replacement':t['target'],'unit_id':uid})
   else:
    if loc['source_pck_sha256']!='17131a6f209694a81c56645a278f371c3dcce53e5ce9369ddb0dfc3867f1215c':raise EvidenceError('원본 PCK 기준 불일치')
    for entry in loc['scenes']:
     for r in entry['units']:
      uid=r['id'];u=units[uid];t=translations[uid]
      if (r['original']!=u['source'] or t['source_hash']!=u['source_hash'] or r['synthetic']!=t['target']
          or r['property'] not in ('text','tooltip_text','placeholder_text')):raise EvidenceError('기존 UI 단위 불일치')
      batch_records.append({'logical':entry['logical'],'original_sha256':entry['original_sha256'],
       'node_path':r['node_path'],'property':r['property'],'original':u['source'],'replacement':t['target'],'unit_id':uid})
   ids=[r['unit_id'] for r in batch_records]
   coords=[(r.get('physical',r.get('logical')),r['node_path'],r['property']) for r in batch_records]
   if len(ids)!=len(set(ids)) or len(coords)!=len(set(coords)):raise EvidenceError('기존 UI 위치 중복')
   for p in paths:_checked(root,snapshot,p)
   records.extend(batch_records)
  except (EvidenceError,OSError,ValueError,KeyError,TypeError,AttributeError,parallel.ToolError) as e:
   if diagnostics is not None:diagnostics[name]=str(e)
 _snapshot(root)
 return records

def resolve_records(root,original,index,diagnostics=None):
 """승인 위치를 실제 원본 PCK entry 바이트에 유일하게 결속한다."""
 root=Path(root);snapshot=_snapshot(root)
 mapping=json.loads(_checked(root,snapshot,MAPPING))
 if mapping['source_sha256']!='17131a6f209694a81c56645a278f371c3dcce53e5ce9369ddb0dfc3867f1215c':raise EvidenceError('기준 매핑 불일치')
 candidates=[r['entry'] for r in mapping['replacements'] if r['entry'].endswith('.scn')]
 if len(candidates)!=len(set(candidates)):raise EvidenceError('기준 매핑 중복')
 hashes={name:_sha(scene._entry(original,index,name)) for name in candidates}
 selected={}; origins={}; conflicts=set()
 for r in approved_records(root,diagnostics):
  if 'physical' in r:
   name=r['physical']
   try:
    if _sha(scene._entry(original,index,name))!=r['original_sha256']:continue
   except (scene.UnsupportedScene,scene.VerificationError):continue
  else:
   matches=[name for name,digest in hashes.items() if digest==r['original_sha256']]
   if len(matches)!=1:continue
   name=matches[0]
  key=(name,r['node_path'],r['property'])
  value={k:r[k] for k in ('node_path','property','original','replacement')}
  if key in origins and origins[key]!=r['unit_id']:
   conflicts.add(key)
  elif key in selected and selected[key]!=value:
   conflicts.add(key)
  else:
   origins[key]=r['unit_id'];selected[key]=value
 for key in conflicts:selected.pop(key,None)
 _checked(root,snapshot,MAPPING);_snapshot(root)
 return selected
