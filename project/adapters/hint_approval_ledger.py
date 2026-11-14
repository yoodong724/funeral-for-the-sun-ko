"""Rebuild the 072 hint approval ledger from the fixed reviewed batch snapshot.

The snapshot digest is a trust anchor; caller-provided policies are never an
approval source. This proves the reviewed locations and strings, not exposure,
rendering, or game behavior.
"""
import hashlib
import json
from pathlib import Path
import tempfile
from scripts import parallel_translations as parallel

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path('scratch/technical/t3-hint-ledger-072/approval-snapshot.json')
SNAPSHOT_SHA256 = '05aac6df917ef73a19703145b4d62c193fa393daa80d78a05d668117037dafb7'
SOURCE = '17131a6f209694a81c56645a278f371c3dcce53e5ce9369ddb0dfc3867f1215c'
PAYLOAD = '23b4b9c3f32a79057fcb5725f76796abb53e0e1be81a53f42af85e919716b56f'


class LedgerError(ValueError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _checked_files(root, paths=()):
    raw = (root / SNAPSHOT).read_bytes()
    if _sha(raw) != SNAPSHOT_SHA256:
        raise LedgerError('승인 스냅샷이 변경됨')
    snapshot = json.loads(raw)
    if snapshot.get('format') != 'funeral-hint-approval-snapshot-v1':
        raise LedgerError('승인 스냅샷 형식이 다름')
    for path in paths:
        if path not in snapshot['files'] or _sha((root / path).read_bytes()) != snapshot['files'][path]:
            raise LedgerError('승인 근거가 변경됨: ' + path)
    return snapshot


def _batch(root, snapshot, num, batch):
    from l10n_primitives.core import revision
    prefix='scratch/batches/' + batch + '/'
    paths=[p for p in snapshot['files'] if p.startswith(prefix)]
    paths += ['scratch/batches/t5-b'+num+'-001/locations.local.json',
              'scratch/batches/t5-b'+num+'-review-001.ko.md']
    if num == '255':
        paths += ['scratch/batches/t5-b255-001/results/hint-display-001.json',
                  'scratch/batches/t5-postfix-b255-b271-b274-b277-review.ko.md']
    _checked_files(root,paths)
    folder = root / prefix
    inputs = parallel.load_inputs(folder / 'catalog.json', root / 'project/canonical/c002', folder / 'plan.json')
    report = json.loads((folder / 'merge-report.json').read_text())
    stored = json.loads((folder / 'merged-reviewed.json').read_text())
    if (not report.get('ok') or not report.get('passed') or not report.get('merged_output_written')
            or report.get('plan_revision') != revision(inputs.plan)
            or report.get('source_revision') != inputs.catalog['source_revision']
            or report.get('canonical_revision') != inputs.canonical_revision
            or report.get('merged_translations_revision') != revision(stored)):
        raise LedgerError('병합 보고서 revision 불일치: ' + batch)
    values=[]
    for task in inputs.plan['tasks']:
        result, value, code = parallel.inspect_task(inputs, task)
        if code or not result['passed'] or value is None:
            raise LedgerError('배정된 번역 기술 검사 실패: ' + batch)
        values.append(value)
    if parallel.merged_translations(inputs, values) != stored:
        raise LedgerError('병합 결과 재계산 불일치: ' + batch)
    units={u['id']:u for u in inputs.catalog['units']}
    translations={x['id']:x for x in stored['translations']}
    locs=json.loads((root / 'scratch/batches' / ('t5-b'+num+'-001') / 'locations.local.json').read_text())
    if len(locs) != len(units) or {x['unit_id'] for x in locs} != set(units):
        raise LedgerError('위치 및 배정 범위 불일치: ' + batch)
    entries={}
    for loc in locs:
        uid=loc['unit_id']; unit=units[uid]; tr=translations[uid]
        field=loc['field']; prop={'question':'hint_question','location':'hint_room_reveal'}.get(field)
        if (loc['property'] != prop or unit['pointer'] != '/hints/' + loc['hint_key'] + '/' + field
                or unit['source_hash'] != loc['source_hash'] or tr['source_hash'] != unit['source_hash']
                or not isinstance(tr['target'],str) or not tr['target']):
            raise LedgerError('원문·번역·위치 불일치: ' + uid)
        entries.setdefault(loc['physical'],[]).append({'resource_id':loc['resource_id'],
            'property':prop,'path':[],'original':unit['source'],'replacement':tr['target']})
    if num == '255':
        old=json.loads((root/'scratch/batches/t5-b255-001/results/hint-display-001.json').read_text())
        new=json.loads((root/'scratch/batches/t5-b255-fix-001/results/hint-display-001.json').read_text())
        oldmap={x['id']:x for x in old['translations']}; newmap={x['id']:x for x in new['translations']}
        if set(oldmap)!=set(newmap) or [k for k in oldmap if oldmap[k]!=newmap[k]] != ['u_fcfa125f27171be39e44d7d7']:
            raise LedgerError('b255 검수 후 수정 범위 불일치')
    _checked_files(root,paths)
    return entries


def build_ledger(root=ROOT, *, diagnostics=None):
    root=Path(root)
    try:
        snapshot=_checked_files(root)
        entries={}
        for num,batch in (('255','t5-b255-fix-001'),('256','t5-b256-001'),
                          ('257','t5-b257-001'),('258','t5-b258-001')):
            try:
                found=_batch(root,snapshot,num,batch)
                if entries.keys() & found.keys():
                    raise LedgerError('배치별 리소스 범위가 중복됨')
                entries.update(found)
            except (LedgerError,OSError,ValueError,KeyError,TypeError,AttributeError,parallel.ToolError) as exc:
                if diagnostics is not None: diagnostics[batch]=str(exc)
        _checked_files(root)
        return {'format':'funeral-rsrc-structural-map-v1','source_sha256':SOURCE,'payload_sha256':PAYLOAD,
                'entries':[{'entry':name,'changes':changes} for name,changes in sorted(entries.items())]}
    except LedgerError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, parallel.ToolError) as exc:
        raise LedgerError('승인 원장 작성 실패: '+str(exc)) from exc


def verify(original, payload, mapping, root=ROOT):
    from project.adapters import payload_rsrc_verify
    diagnostics = {}
    ledger = build_ledger(root, diagnostics=diagnostics)
    if not ledger['entries']:
        return {'status':'partial','entries':[],'entries_checked':0,'listed_strings':0,
                'approval':'fixed_reviewed_batches_and_recomputed_merge','unapproved_batches':diagnostics}
    with tempfile.TemporaryDirectory(prefix='funeral-approved-hints-') as tmp:
        path=Path(tmp)/'generated.json'
        path.write_text(json.dumps(ledger,ensure_ascii=False),encoding='utf-8')
        result=payload_rsrc_verify.verify_selected_hints(original,payload,mapping,path)
    result['approval']='fixed_reviewed_batches_and_recomputed_merge'
    result['unapproved_batches']=diagnostics
    return result
