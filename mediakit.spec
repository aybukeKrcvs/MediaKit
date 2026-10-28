# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules



a = Analysis(
    ['src\\mediakit\\__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('src/mediakit/assets', 'mediakit/assets'),
    ],
    # onnxruntime loads its execution providers by name at runtime, so
    # PyInstaller cannot see them in the import graph.
    hiddenimports=[
        'onnxruntime',
        'onnxruntime.capi._pybind_state',
        'onnxruntime.capi.onnxruntime_validation',
        # PyAV is mostly compiled Cython modules that import each other
        # from C, which PyInstaller's import scanner cannot follow.
        *collect_submodules('av'),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Pulled in by numpy/Pillow/onnxruntime but never used by the app.
    # Each one costs tens of MB in the installer.
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'pytest',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtWebEngineCore',
        'PySide6.Qt3DCore',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia',
        'PySide6.QtPdf',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mediakit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no console window behind it
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
    upx=False,
    upx_exclude=[],
    name='mediakit',
)
