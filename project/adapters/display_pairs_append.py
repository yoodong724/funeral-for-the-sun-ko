"""Append checked page translations to the game's display-only pair table.

The original English strings and translations stay in local, ignored inputs.
The caller supplies the complete page catalog to prevent a source-text match
from changing an unselected page with the same English text.
"""
import argparse
import hashlib
import json
from pathlib import Path

HEADER = "const _KO_INTRO_DISPLAY_PAIRS = [\n"
FOOTER = "\n]\n\nfunc ko_flashback_display"


def append_pairs(script, catalog, complete_catalog, translations):
    if catalog['source_revision'] != translations['source_revision']:
        raise ValueError('catalog and translation revisions differ')
    units = {unit['id']: unit for unit in catalog['units']}
    rows = translations['translations']
    if len(units) != len(catalog['units']) or len(rows) != len(units):
        raise ValueError('duplicate or missing translation units')
    targets = {}
    for row in rows:
        unit = units.pop(row['id'])
        source = unit['source']
        digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        if digest != row['source_hash'] or digest != unit['source_hash']:
            raise ValueError('source hash mismatch')
        if not isinstance(row['target'], str) or not row['target']:
            raise ValueError('empty translation')
        if source in targets:
            raise ValueError('duplicate selected source text')
        targets[source] = row['target']
    selected_ids = {row['id'] for row in rows}
    for unit in complete_catalog['units']:
        if unit['source'] in targets and unit['id'] not in selected_ids:
            raise ValueError('source text is shared with an unselected unit')
    if script.count(HEADER) != 1 or script.count(FOOTER) != 1:
        raise ValueError('display table is missing or ambiguous')
    start = script.index(HEADER) + len(HEADER)
    end = script.index(FOOTER, start)
    body = script[start:end]
    existing = set()
    for line in body.splitlines():
        try:
            pair = json.loads(line.strip().removesuffix(','))
        except json.JSONDecodeError as exc:
            raise ValueError('unsupported display table row') from exc
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError('unsupported display table row')
        existing.add(pair[0])
    if existing.intersection(targets):
        raise ValueError('translation already has a display entry')
    lines = [json.dumps([source, target], ensure_ascii=False) for source, target in targets.items()]
    return script[:end] + ',\n\t' + ',\n\t'.join(lines) + script[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', required=True, type=Path)
    parser.add_argument('--catalog', required=True, type=Path)
    parser.add_argument('--complete-catalog', required=True, type=Path)
    parser.add_argument('--translations', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    result = append_pairs(args.script.read_text(encoding='utf-8'), load(args.catalog),
                          load(args.complete_catalog), load(args.translations))
    with args.out.open('x', encoding='utf-8') as stream:
        stream.write(result)
    print(f"표시 문구 {len(load(args.translations)['translations'])}건 추가")


if __name__ == '__main__':
    main()
