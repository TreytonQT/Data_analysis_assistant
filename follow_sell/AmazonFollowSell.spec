import os
from pathlib import Path

project = Path(SPECPATH).parent
resources = os.environ['FOLLOW_SELL_RESOURCES']
web = os.environ['FOLLOW_SELL_WEB']
a = Analysis(
    [str(project / 'follow_sell/launcher.py')], pathex=[str(project)], binaries=[],
    datas=[(str(Path(resources) / 'oa_schema.json'), 'follow_sell/resources'),
           (str(Path(resources) / 'oa_output.xlsx'), 'follow_sell/resources'),
           *[(str(file), 'follow_sell/resources/templates') for file in (Path(resources) / 'templates').glob('*.xlsx')],
           (web, 'follow_sell/web')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['backend', 'dashboard', 'pandas', 'numpy', 'scipy', 'matplotlib', 'IPython', 'pytest'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AmazonFollowSell', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AmazonFollowSell')
