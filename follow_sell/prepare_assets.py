"""Read the supplied references; emit only headers and one sample per input."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path.home() / 'Desktop')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work = args.output / 'work'
    resources = work / 'resources'
    resources.mkdir(parents=True, exist_ok=True)
    snapshot = {}
    hashes = {}
    for number in [1, 2, 3, 4, 5, '结果1', '结果2']:
        file = next(args.source.glob(f'【{number}】*.xlsx'))
        hashes[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
        if number == '结果2':
            continue
        wb = load_workbook(file, data_only=True)
        ws = wb.worksheets[0]
        header = [cell.value for cell in ws[1]]
        while header and header[-1] is None:
            header.pop()
        data = next(list(row)[:len(header)] for row in ws.iter_rows(min_row=2, values_only=True)
                    if any(value is not None and value != '' for value in row))
        snapshot[str(number)] = {'filename': file.name, 'headers': header, 'sample': data,
                                 'widths': [min(35, max(12, ws.column_dimensions[cell.column_letter].width or 12))
                                            for cell in ws[1][:len(header)]]}
        wb.close()
    (work / 'asset_snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
    (work / 'original_hashes.json').write_text(json.dumps(hashes, ensure_ascii=False), encoding='utf-8')
    schema = {'headers': snapshot['结果1']['headers'], 'descriptions': snapshot['结果1']['sample']}
    (resources / 'oa_schema.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Prepared 5 one-row examples, OA header schema and 7 original checksums.')


if __name__ == '__main__':
    main()
