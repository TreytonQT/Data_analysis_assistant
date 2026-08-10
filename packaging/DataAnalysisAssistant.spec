import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


spec_dir = Path(SPECPATH)
project_root = spec_dir.parent
hidden_imports = collect_submodules("uvicorn")
frontend_dist = os.environ.get("FRONTEND_DIST_DIR", str(project_root / "frontend" / "dist"))

a = Analysis(
    [str(spec_dir / "windows_launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(frontend_dist, "frontend/dist")],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DataAnalysisAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DataAnalysisAssistant",
)
