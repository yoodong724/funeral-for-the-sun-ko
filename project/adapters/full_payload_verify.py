"""Combine entry-level protection results without promoting unsupported entries.

The caller supplies results produced by actual byte/structure verifiers. This
module does not inspect a PCK or decide whether a proposed change is approved.
"""

from pathlib import PurePosixPath


class FullVerificationError(ValueError):
    """The collected entry results are inconsistent with the replacement map."""


def projection_chain_result(origin, projection, origin_result, projection_result,
                            *, original_sha256, payload_sha256, expected):
    """Join two already-executed projection verifiers through the same baseline."""
    if (origin_result.get('status') != 'selected_origin_passed'
            or projection_result.get('status') != 'selected_projection_passed'):
        raise FullVerificationError('projection chain verification did not pass')
    entry = origin.get('entry')
    hashes = (original_sha256, payload_sha256, origin.get('original_pck_sha256'),
              origin.get('baseline_pck_sha256'), origin.get('baseline_gdc_sha256'),
              projection.get('baseline_sha256'), projection.get('baseline_entry_sha256'),
              projection.get('payload_sha256'), projection.get('payload_entry_sha256'))
    if (not isinstance(entry, str) or not entry or entry not in expected
            or any(not isinstance(value, str) or not value for value in hashes)
            or entry != projection.get('entry')
            or origin.get('original_pck_sha256') != original_sha256
            or origin.get('baseline_pck_sha256') != projection.get('baseline_sha256')
            or origin.get('baseline_gdc_sha256') != projection.get('baseline_entry_sha256')
            or projection.get('payload_sha256') != payload_sha256
            or expected.get(entry) != projection.get('payload_entry_sha256')):
        raise FullVerificationError('projection chain does not share the same PCK entries')
    return {'entry': entry, 'status': 'passed',
            'reason': '승인 helper 원본→기준 및 기준→최종 표시 투영; helper 의미는 승인 입력'}


def classify_entries(expected, *, hint_report=None, gdc_report=None, additional=(), hint_approved=False, gdc_approved_entries=()):
    """Return one outcome for every mapped replacement.

    ``additional`` is an internal sequence of actual verifier outcomes, not an
    authorization manifest or a list supplied by an end user.
    """
    if not isinstance(expected, dict) or not expected:
        raise FullVerificationError('replacement map must not be empty')
    results = {}
    for name in expected:
        if not isinstance(name, str) or not name:
            raise FullVerificationError('invalid replacement entry')
        results[name] = {
            'entry': name,
            'type': PurePosixPath(name).suffix.lower() or '(확장자 없음)',
            'status': 'unsupported',
            'reason': '이 entry의 원본부터 최종까지 보호 구조 검증이 지원되지 않음',
        }

    def apply(name, status, reason):
        if name not in results:
            raise FullVerificationError('verification result is not a mapped entry')
        if name in classified:
            raise FullVerificationError('duplicate entry verification result')
        if status not in ('passed', 'unsupported', 'failed') or not isinstance(reason, str) or not reason:
            raise FullVerificationError('invalid entry verification result')
        classified.add(name)
        results[name]['status'] = status
        results[name]['reason'] = reason

    classified = set()
    gdc_approved_entries = set(gdc_approved_entries)
    selected_gdc = {item.get('entry') for item in gdc_report.get('entries', [])} if isinstance(gdc_report, dict) else set()
    if not gdc_approved_entries.issubset(selected_gdc):
        raise FullVerificationError('approved GDC is outside selected verification scope')
    for report, expected_status, suffix, label in (
        (hint_report, 'partial', '.res', '승인 힌트 String과 비대상 직렬화 구조'),
        (gdc_report, 'selected_scripts_passed', '.gdc', '승인 표시 토큰과 비대상 토큰'),
    ):
        if report is None:
            continue
        if not isinstance(report, dict) or report.get('status') != expected_status or not isinstance(report.get('entries'), list):
            raise FullVerificationError('selected verifier did not pass')
        for item in report['entries']:
            if not isinstance(item, dict) or not isinstance(item.get('entry'), str) or not item['entry'].endswith(suffix):
                raise FullVerificationError('invalid selected verifier entry')
            if suffix == '.res' and hint_approved:
                apply(item['entry'], 'passed', '검수된 고정 배치 병합·위치 및 원본→최종 구조 검증')
            elif suffix == '.gdc' and item['entry'] in gdc_approved_entries:
                apply(item['entry'], 'passed', '검수된 고정 배치 병합·토큰 위치 및 원본→최종 구조 검증')
            else:
                apply(item['entry'], 'unsupported', label + ' 비교는 통과했으나 승인 근거가 독립 결속되지 않음')

    for item in additional:
        if not isinstance(item, dict) or set(item) != {'entry', 'status', 'reason'}:
            raise FullVerificationError('invalid additional verifier result')
        apply(item['entry'], item['status'], item['reason'])

    entries = list(results.values())
    counts = {status: sum(row['status'] == status for row in entries)
              for status in ('passed', 'unsupported', 'failed')}
    status = 'failed' if counts['failed'] else 'unsupported' if counts['unsupported'] else 'passed'
    return {'status': status, 'entry_count': len(entries), 'counts': counts, 'entries': entries}
