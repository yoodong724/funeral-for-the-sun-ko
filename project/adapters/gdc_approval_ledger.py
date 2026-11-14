"""Recompute fixed GDC approvals and join them to source token evidence.

Fixed reviewed snapshots cover the original six and separately checked
residual entries. Historical localization evidence binds line/column to native
indices; actual GDC token and constant comparison is run again on both PCKs.
"""
import hashlib
import json
from pathlib import Path
import tempfile
from collections import Counter
from scripts import parallel_translations as parallel
from l10n_primitives.core import revision
from project.adapters import gdc_payload_verify

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path('scratch/technical/t3-gdc-ledger-072/approval-snapshot.json')
SNAPSHOT_SHA256 = '2ca0adbabd541e1386fee9e527fde30367443b84442abd1eb2e9e04c5ad0e76a'
SOURCE = '17131a6f209694a81c56645a278f371c3dcce53e5ce9369ddb0dfc3867f1215c'
PAYLOAD = '23b4b9c3f32a79057fcb5725f76796abb53e0e1be81a53f42af85e919716b56f'
INVENTORY = 'project/context/script-inventory-26591563/occurrences.local.jsonl'

class LedgerError(ValueError):
    pass

def _sha(data): return hashlib.sha256(data).hexdigest()

def _snapshot(root):
    raw = (root / SNAPSHOT).read_bytes()
    if _sha(raw) != SNAPSHOT_SHA256: raise LedgerError('고정 승인 스냅샷 불일치')
    result = json.loads(raw)
    if result.get('format') != 'funeral-gdc-approval-snapshot-v1': raise LedgerError('원장 형식 불일치')
    return result

def _read(root, snapshot, name):
    name = str(name)
    raw = (root / name).read_bytes()
    if name not in snapshot['files'] or _sha(raw) != snapshot['files'][name]:
        raise LedgerError('승인 근거가 변경됨: ' + name)
    return raw

def _batch(root, snapshot, number):
    if number == '279': directory, task, locbase = 't5-b279-partial-001', 'b279-partial-001', 't5-b279-001'
    elif number == '281': directory, task, locbase = 't5-b281-001', 'b281-001', 't5-b281-001'
    else: raise LedgerError('미지원 배치')
    base = Path('scratch/batches') / directory
    paths = [base / n for n in ('catalog.json','plan.json','merge-report.json','merged-reviewed.json',f'results/{task}.json')]
    paths += [Path('scratch/batches')/locbase/'locations.local.json',Path(f'scratch/batches/t5-b{number}-review-001.ko.md')]
    if number == '279': paths.append(base/'결속.ko.md')
    for p in paths: _read(root,snapshot,p)
    for p in snapshot['files']:
        if p.startswith('project/canonical/c002/'): _read(root,snapshot,p)
    inputs=parallel.load_inputs(root/base/'catalog.json',root/'project/canonical/c002',root/base/'plan.json')
    report=json.loads(_read(root,snapshot,base/'merge-report.json'))
    merged=json.loads(_read(root,snapshot,base/'merged-reviewed.json'))
    if (not report.get('ok') or not report.get('passed') or not report.get('merged_output_written')
        or report.get('plan_revision')!=revision(inputs.plan)
        or report.get('source_revision')!=inputs.catalog['source_revision']
        or report.get('canonical_revision')!=inputs.canonical_revision
        or report.get('merged_translations_revision')!=revision(merged)):
        raise LedgerError('병합 revision 불일치')
    values=[]
    for assignment in inputs.plan['tasks']:
        status,value,code=parallel.inspect_task(inputs,assignment)
        if code or not status['passed'] or value is None: raise LedgerError('배치 기술 검사 실패')
        values.append(value)
    if parallel.merged_translations(inputs,values)!=merged: raise LedgerError('병합 결과 불일치')
    catalog={x['id']:x for x in inputs.catalog['units']}
    targets={x['id']:x for x in merged['translations']}
    locations=json.loads(_read(root,snapshot,Path('scratch/batches')/locbase/'locations.local.json'))
    result={}
    for loc in locations:
        key=(loc.get('pck_path'),loc.get('line'),loc.get('column'))
        units=[u for u in catalog.values() if u['pointer']=='/'+loc['key']]
        if len(units)!=1 or units[0]['id'] not in targets: continue
        u=units[0]; t=targets[u['id']]
        if (u['source_hash']!=loc.get('source_utf8_sha256') or t['source_hash']!=u['source_hash']
            or _sha(u['source'].encode())!=u['source_hash'] or not isinstance(t.get('target'),str)):
            raise LedgerError('문안·원문 해시 불일치')
        if key in result: raise LedgerError('배치 내 중복 위치')
        result[key]=(loc,u['source'],t['target'])
    for p in paths: _read(root,snapshot,p)
    return result

def build_ledger(root=ROOT, diagnostics=None):
    root=Path(root); snapshot=_snapshot(root)
    try:
        rows=[json.loads(line) for line in _read(root,snapshot,INVENTORY).splitlines()]
        byid={x['candidate_id']:x for x in rows}
        if len(byid)!=len(rows): raise LedgerError('스크립트 위치 ID 중복')
        coordinates=Counter((x.get('pck_path'),x.get('line'),x.get('column')) for x in rows)
        cache={}; entries=[]
        for item in snapshot['entries']:
            try:
                b=item['batch']
                if b not in cache: cache[b]=_batch(root,snapshot,b)
                plan_raw=_read(root,snapshot,item['plan']); plan=json.loads(plan_raw)
                proof=json.loads(_read(root,snapshot,item['verification']))
                if (proof.get('format')!='gdscript-display-result-v1'
                    or proof.get('source_sha256')!=plan['source_sha256']
                    or proof.get('request_sha256')!=_sha(plan_raw)
                    or proof.get('candidate_sha256')!=item['candidate_sha256']
                    or proof.get('selected_occurrences')!=len(plan['changes'])
                    or proof.get('selected_token_indices')!=sorted(c['token_index'] for c in plan['changes'])
                    or any(proof.get(k)!=0 for k in ('non_target_token_bytes_changed','non_target_constant_bytes_changed','line_column_map_bytes_changed'))):
                    raise LedgerError('원본 토큰 위치 검사 근거 불일치')
                seen=set()
                for change in plan['changes']:
                    key=(item['entry'],change['line'],change['column'])
                    if key in seen or coordinates[key]!=1 or key not in cache[b]: raise LedgerError('토큰 위치 1:1 불일치')
                    seen.add(key); loc, original, target=cache[b][key]
                    inv=byid.get(loc.get('candidate_id'))
                    if (inv is None or any(inv.get(k)!=loc.get(k) for k in ('pck_path','line','column','source_utf8_sha256','source_sha256'))
                        or loc.get('source_sha256')!=plan['source_sha256']
                        or original!=change['original'] or target!=change['replacement']):
                        raise LedgerError('승인 문안·토큰 좌표 불일치')
                entries.append({'entry':item['entry'],'stages':[{'plan':plan,'candidate_sha256':item['candidate_sha256']}]})
            except (LedgerError,OSError,ValueError,KeyError,TypeError,AttributeError,parallel.ToolError) as exc:
                if diagnostics is not None:diagnostics[item.get('entry','?')]=str(exc)
        _read(root,snapshot,INVENTORY);_snapshot(root)
        from project.adapters import gdc_residual_ledger as residual
        try:
            extra=residual.build_entries(root,diagnostics)
            if {item['entry'] for item in extra} & {item['entry'] for item in entries}:
                raise residual.LedgerError('승인 GDC 원장 범위 중복')
            entries.extend(extra)
        except (residual.LedgerError,OSError,ValueError,KeyError,TypeError) as exc:
            if diagnostics is not None: diagnostics['residual_ledger']=str(exc)
        return {'format':'funeral-gdc-structural-map-v1','source_sha256':SOURCE,'payload_sha256':PAYLOAD,'entries':entries}
    except (OSError,ValueError,KeyError,TypeError,AttributeError,parallel.ToolError) as exc:
        if isinstance(exc,LedgerError):raise
        raise LedgerError('GDC 승인 원장 실패: '+str(exc)) from exc

def verify(original,payload,gdre,probe,root=ROOT):
    diagnostics={}; ledger=build_ledger(root,diagnostics)
    if not ledger['entries']:
        return {'status':'selected_scripts_passed','entries':[],'unapproved_entries':diagnostics}
    with tempfile.TemporaryDirectory(prefix='gdc-approved-ledger-') as tmp:
        path=Path(tmp)/'generated.json'
        path.write_text(json.dumps(ledger,ensure_ascii=False),encoding='utf-8')
        from project.adapters import gdc_residual_ledger as residual
        if any('intermediate_file' in stage for entry in ledger['entries'] for stage in entry['stages']):
            try:
                snapshot=residual._snapshot(Path(root))
                for entry in ledger['entries']:
                    for stage in entry['stages']:
                        if 'intermediate_file' in stage:
                            name=stage['intermediate_file']
                            source=Path('scratch/technical/t5-milestone-072')/name
                            data=residual._read(Path(root),snapshot,source)
                            if residual._sha(data)!=stage['candidate_sha256']:
                                raise LedgerError('중간 GDC 해시 불일치')
                            (Path(tmp)/name).write_bytes(data)
            except (residual.LedgerError,OSError) as exc:
                raise LedgerError('중간 GDC 검증 실패: '+str(exc)) from exc
        result=gdc_payload_verify.verify(original,payload,path,gdre,probe)
    result['approval']='fixed_reviewed_batches_and_recomputed_merge_with_token_location_proof'
    result['unapproved_entries']=diagnostics
    return result
