# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['yaml', 'PIL', 'PIL.Image', 'requests', 'tqdm', 'cv2', 'pptx', 'pillow_heif', 'wakepy', 'gradio_client']
hiddenimports += collect_submodules('handlers')
hiddenimports += collect_submodules('PIL')
hiddenimports += collect_submodules('pptx')


a = Analysis(
    ['/Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Scripts/gui_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('/Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Scripts/core', 'core'), ('/Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Scripts/config', 'config'), ('/Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Scripts/handlers', 'handlers'), ('/Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Scripts/templates', 'templates')],
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='GAI_Launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
app = BUNDLE(
    exe,
    name='GAI_Launcher.app',
    icon=None,
    bundle_identifier=None,
)
