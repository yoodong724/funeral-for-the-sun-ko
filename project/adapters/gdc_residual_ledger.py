"""Bind seven fixed 072 GDC chains to reviewed batches and token evidence.

The immutable snapshot is the trust anchor, not a caller-provided policy.
Previously recorded coordinate-to-token evidence is reused, not re-derived.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts import parallel_translations as parallel
from l10n_primitives.core import revision

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path('scratch/technical/t3-gdc-residual-072/approval-snapshot.json')
SNAPSHOT_SHA256 = '730310ce775e36401fb7dd9fe02f5f339eb900e5213ed1af95a283e278c40157'
INVENTORY = 'project/context/script-inventory-26591563/occurrences.local.jsonl'
GDC_MAP = 'scratch/technical/t5-milestone-072/gdc-structural-map.local.json'
EARLY_MAP = 'scratch/technical/attempt-002/script-display-candidate/manifest.local.json'
EARLY_PROOF = 'scratch/technical/attempt-002/script-display-candidate/verification.json'
STAGES = {
 'Solanor/Scenes/ui/pause_menu.gdc': [('b001',None,None)],
 'Solanor/main_menu.gdc': [('b001',None,None)],
 'Solanor/saved_game/SaveManager.gdc': [('b001',None,None)],
 'Solanor/UI/book/book2/Hints/hint_tab.gdc': [('b002',None,None),('b304','scratch/technical/t5-b304-resource/plan.json','scratch/technical/t5-b304-resource/candidate/verification.json')],
 'Solanor/safe_room.gdc': [('b279','scratch/technical/t5-b279-resource/plan-3.json','scratch/technical/t5-b279-resource/candidate-3/verification.json'),('b303','scratch/technical/t5-b303-resource/plan.json','scratch/technical/t5-b303-resource/candidate/verification.json')],
 'Solanor/river.gdc': [('river','scratch/technical/t5-river-tutorial/request.json','scratch/technical/t5-river-tutorial/candidate/verification.json')],
 'Solanor/UI/book/book2/progresspage/name_unlock.gdc': [('notify','scratch/technical/t5-name-notification-001/script-plan.json','scratch/technical/t5-name-notification-001/script-candidate/verification.json')],
}

class LedgerError(ValueError): pass

def _sha(data): return hashlib.sha256(data).hexdigest()

def _snapshot(root):
    data=(root/SNAPSHOT).read_bytes()
    if _sha(data)!=SNAPSHOT_SHA256: raise LedgerError('고정 승인 스냅샷 불일치')
    obj=json.loads(data)
    if obj.get('format')!='funeral-gdc-residual-approval-v1': raise LedgerError('승인 스냅샷 형식 불일치')
    return obj

def _read(root,snapshot,path):
    path=str(path)
    if path not in snapshot['files']: raise LedgerError('승인 스냅샷 밖 자료: '+path)
    data=(root/path).read_bytes()
    if _sha(data)!=snapshot['files'][path]: raise LedgerError('승인 자료 변경: '+path)
    return data

def _batch(root,snapshot,name):
    cfg=snapshot['batches'][name]; base=Path(cfg['base']); catalog=Path(cfg['catalog'])
    files=[catalog,base/cfg['plan'],base/cfg['report'],base/cfg['merged'],Path(cfg['review'])]
    plan=json.loads(_read(root,snapshot,base/cfg['plan']))
    files += [base/task['translations'] for task in plan['tasks']]
    canon=Path('project/canonical')/cfg['canonical']
    files += [Path(p) for p in snapshot['files'] if p.startswith(str(canon)+'/')]
    for p in files:_read(root,snapshot,p)
    inputs=parallel.load_inputs(root/catalog,root/canon,root/base/cfg['plan'])
    report=json.loads(_read(root,snapshot,base/cfg['report']))
    merged=json.loads(_read(root,snapshot,base/cfg['merged']))
    if (not report.get('ok') or not report.get('passed') or not report.get('merged_output_written')
        or report.get('plan_revision')!=revision(inputs.plan)
        or report.get('source_revision')!=inputs.catalog['source_revision']
        or report.get('canonical_revision')!=inputs.canonical_revision
        or report.get('merged_translations_revision')!=revision(merged)):
        raise LedgerError('배치 revision 불일치: '+name)
    vals=[]
    for task in inputs.plan['tasks']:
        status,val,code=parallel.inspect_task(inputs,task)
        if code or not status['passed'] or val is None: raise LedgerError('배치 검사 실패: '+name)
        vals.append(val)
    if parallel.merged_translations(inputs,vals)!=merged: raise LedgerError('병합 결과 불일치: '+name)
    units={u['id']:u for u in inputs.catalog['units']}
    translations={v['id']:v for v in merged['translations']}
    if len(units)!=len(inputs.catalog['units']) or len(translations)!=len(merged['translations']):raise LedgerError('중복 unit')
    result={}
    for uid,tr in translations.items():
        u=units[uid]
        if tr['source_hash']!=u['source_hash'] or _sha(u['source'].encode())!=u['source_hash'] or not isinstance(tr['target'],str):
            raise LedgerError('원문 또는 번역 불일치')
        result[uid]=(u['source_hash'],tr['target'])
    for p in files:_read(root,snapshot,p)
    return result

def _proof(root,snapshot,stage,plan_path,proof_path):
    plan_raw=_read(root,snapshot,plan_path);plan=json.loads(plan_raw);proof=json.loads(_read(root,snapshot,proof_path))
    if (plan!=stage['plan'] or proof.get('format')!='gdscript-display-result-v1'
        or proof.get('source_sha256')!=plan['source_sha256'] or proof.get('request_sha256')!=_sha(plan_raw)
        or proof.get('candidate_sha256')!=stage['candidate_sha256']
        or proof.get('selected_occurrences')!=len(plan['changes'])
        or proof.get('selected_token_indices')!=sorted(x['token_index'] for x in plan['changes'])
        or any(proof.get(k)!=0 for k in ('non_target_token_bytes_changed','non_target_constant_bytes_changed','line_column_map_bytes_changed'))):
        raise LedgerError('토큰 검사 근거 불일치')

def build_entries(root=ROOT, diagnostics=None):
    root=Path(root);snapshot=_snapshot(root)
    try:
        rows=[json.loads(line) for line in _read(root,snapshot,INVENTORY).splitlines()]
        coords=Counter((r.get('pck_path'),r.get('line'),r.get('column')) for r in rows)
        bycoord={(r.get('pck_path'),r.get('line'),r.get('column')):r for r in rows}
        early=json.loads(_read(root,snapshot,EARLY_MAP)); earlyproof=json.loads(_read(root,snapshot,EARLY_PROOF))
        emap=early['units']; emeta={r['pck_path']:r for r in early['files']}
        oldproof={r['file']:r for r in earlyproof['scripts']}
        structural=json.loads(_read(root,snapshot,GDC_MAP))
        entries={r['entry']:r for r in structural['entries']}
        if len(entries)!=len(structural['entries']):raise LedgerError('GDC 중복 entry')
        cache={}; result=[]
        for entry,stages in STAGES.items():
            try:
                row=entries[entry]; actual=row['stages']
                if len(actual)!=len(stages):raise LedgerError('단계 수 불일치')
                for index,(batch,plan_path,proof_path) in enumerate(stages):
                    if batch not in cache:cache[batch]=_batch(root,snapshot,batch)
                    approved=cache[batch]; st=actual[index];plan=st['plan']
                    if index and plan['source_sha256']!=actual[index-1]['candidate_sha256']:
                        raise LedgerError('단계 바이트 연결 불일치')
                    if plan_path:_proof(root,snapshot,st,plan_path,proof_path)
                    else:
                        prior=oldproof.get(Path(entry).name,{}); meta=emeta.get(entry,{})
                        if (prior.get('raw_sha256')!=plan['source_sha256'] or prior.get('candidate_sha256')!=st['candidate_sha256']
                            or prior.get('allowed')!=len(plan['changes']) or meta.get('sha256')!=plan['source_sha256']
                            or meta.get('count')!=len(plan['changes'])
                            or not all(earlyproof.get('negative_controls',{}).values())):
                            raise LedgerError('기존 토큰 검사 불일치')
                    seen=set()
                    for c in plan['changes']:
                        key=(entry,c['line'],c['column']); src=_sha(c['original'].encode())
                        if coords[key]!=1 or key in seen:raise LedgerError('위치 유일성 불일치')
                        seen.add(key); inv=bycoord[key]
                        if inv.get('source_sha256')!=actual[0]['plan']['source_sha256'] or inv.get('source_utf8_sha256')!=src:
                            raise LedgerError('원본 inventory 해시 불일치')
                        if plan_path:
                            ids=[uid for uid,pair in approved.items() if pair==(src,c['replacement'])]
                            if len(ids)!=1:raise LedgerError('승인 문안 1:1 불일치')
                            if batch in ('b279','b303','b304'):
                                locbase={'b279':'scratch/batches/t5-b279-001','b303':'scratch/batches/t5-b303-001','b304':'scratch/batches/t5-b304-001'}[batch]
                                locs=json.loads(_read(root,snapshot,locbase+'/locations.local.json'))
                                candidates=[v for v in locs if (v.get('pck_path'),v.get('line'),v.get('column'))==key]
                                if len(candidates)!=1 or candidates[0].get('candidate_id')!=inv.get('candidate_id') or candidates[0].get('source_utf8_sha256')!=src:
                                    raise LedgerError('배치 위치 결속 실패')
                        else:
                            matches=[u for u in emap if (u.get('pck_path'),u.get('new_line'),u.get('column'))==key]
                            if (len(matches)!=1 or matches[0].get('new_token_index')!=c['token_index']
                                or matches[0].get('new_source_sha256')!=plan['source_sha256']
                                or matches[0].get('source_hash')!=src or matches[0].get('source')!=c['original']
                                or matches[0].get('target')!=c['replacement']
                                or approved.get(matches[0].get('id'))!=(src,c['replacement'])):
                                raise LedgerError('승인 문안·토큰 좌표 불일치')
                    if index<len(actual)-1:
                        inter=Path('scratch/technical/t5-milestone-072')/st['intermediate_file']
                        if _sha(_read(root,snapshot,inter))!=st['candidate_sha256']:raise LedgerError('중간 GDC 불일치')
                result.append(row)
            except (LedgerError,OSError,ValueError,KeyError,TypeError,AttributeError,parallel.ToolError) as exc:
                if diagnostics is not None:diagnostics[entry]=str(exc)
        for path in (INVENTORY,GDC_MAP,EARLY_MAP,EARLY_PROOF):_read(root,snapshot,path)
        _snapshot(root)
        return result
    except (OSError,ValueError,KeyError,TypeError,AttributeError,parallel.ToolError) as exc:
        if isinstance(exc,LedgerError):raise
        raise LedgerError('추가 GDC 원장 실패: '+str(exc)) from exc
