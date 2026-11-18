from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
import argparse
import hashlib
import json

from openpyxl import load_workbook

from follow_sell.processor import INVENTORY, MABANG_FIELDS, VIRTUAL, process_mabang, process_oa


def rows(content):
    wb = load_workbook(BytesIO(content), data_only=True)
    values = list(wb.worksheets[0].values)
    wb.close()
    return values


def comparable(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path.home() / 'Desktop')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    files = {str(n): next(args.source.glob(f'【{n}】*.xlsx')) for n in [1, 2, 3, 4, 5, '结果1', '结果2']}
    data = {k: v.read_bytes() for k, v in files.items()}
    resources = args.output / 'work/resources'
    oa = process_oa(data['1'], data['2'], data['3'], [files[str(n)].name for n in [1, 2, 3]], resources)
    mabang = process_mabang(data['1'], data['4'], data['5'], [files[str(n)].name for n in [1, 4, 5]])
    actual = rows(oa.content); expected = rows(data['结果1'])
    assert len(actual) == 115 and len(actual[0]) == 102
    assert [list(r) for r in actual[:2]] == [list(r[:102]) for r in expected[:2]]
    for a, e in zip(actual[2:], expected[2:]):
        assert [comparable(v) for v in a] == [comparable(v) for v in e[1:103]], (a[0], 'OA mismatch')
    target, reference, source = rows(mabang.content), rows(data['结果2']), rows(data['4'])
    assert len(target) == 114 and len(target[0]) == 79
    zero_corrections = 0
    business = set(MABANG_FIELDS.values())
    for a, e, original in zip(target[1:], reference[1:], source[1:]):
        for h, av, ev, ov in zip(target[0], a, e, original):
            if comparable(av) != comparable(ev):
                assert av is None and ev in ('0', 0), (a[0], h, av, ev)
                zero_corrections += 1
            if h not in business:
                assert av == ov, (a[0], h, 'unintended change')
    assert zero_corrections == 19, zero_corrections
    for number in range(1, 6):
        file = next((args.output / '模板').glob(f'【{number}】*.xlsx'))
        wb = load_workbook(file)
        assert wb.active.max_row == 2
        assert all(cell.font.color and cell.font.color.type == 'rgb' and cell.font.color.rgb[-6:] == 'FF0000' for cell in wb.active[2])
        wb.close()
    baseline = json.loads((args.output / 'work/original_hashes.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256(Path(file).read_bytes()).hexdigest() == digest for file, digest in baseline.items())
    result_dir = args.output / '验收结果'
    result_dir.mkdir(exist_ok=True)
    (result_dir / oa.filename).write_bytes(oa.content)
    (result_dir / mabang.filename).write_bytes(mabang.content)
    report = {'oa_rows': 113, 'oa_columns': 102, 'mabang_rows': 113, 'mabang_columns': 79,
              'blank_zero_corrections': zero_corrections, 'templates': 5, 'originals_unchanged': 7}
    (args.output / 'work/sample_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
