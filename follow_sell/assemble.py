from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
from pathlib import Path
import shutil
import zipfile

from openpyxl import load_workbook

from follow_sell import VERSION

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.output / 'work' / f'v{VERSION}' / 'dist/AmazonFollowSell'
    delivery = args.output / f'便携程序-v{VERSION}'
    delivery.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'AmazonFollowSell.exe', delivery / 'AmazonFollowSell.exe')
    shutil.copytree(source / '_internal', delivery / '_internal', dirs_exist_ok=True)
    shutil.copytree(args.output / '模板', delivery / '模板', dirs_exist_ok=True)
    usage = Path(__file__).with_name('使用说明.txt').read_text(encoding='utf-8')
    (delivery / '使用说明.txt').write_text(usage, encoding='utf-8-sig')
    (args.output / '使用说明.txt').write_text(usage, encoding='utf-8-sig')
    resources = delivery / '_internal/follow_sell/resources'
    assert len(list((resources / 'templates').glob('*.xlsx'))) == 5
    assert not list(resources.rglob('*.ndjson'))
    files = [delivery / 'AmazonFollowSell.exe', delivery / '使用说明.txt']
    files += [file for folder in ['_internal', '模板'] for file in (delivery / folder).rglob('*') if file.is_file()]
    assert not any(file.suffix.lower() in {'.sqlite', '.sqlite3', '.db'} for file in files)
    archive = args.output / f'AmazonFollowSell-windows-x64-v{VERSION}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(files):
            bundle.write(file, str(Path('AmazonFollowSell') / file.relative_to(delivery)))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        books = [name for name in bundle.namelist() if name.endswith('.xlsx')]
        assert len(books) == 11
        for name in books:
            wb = load_workbook(BytesIO(bundle.read(name)), read_only=True)
            # Artifact exports may omit optional dimension metadata; count real rows.
            assert all(sum(1 for _ in sheet.iter_rows(values_only=True)) == 2 for sheet in wb)
            wb.close()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'{archive}: {archive.stat().st_size / 1024 / 1024:.1f} MB; {len(files)} files; SHA256 {digest}')


if __name__ == '__main__':
    main()
