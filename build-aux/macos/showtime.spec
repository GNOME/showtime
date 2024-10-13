# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ["../../_build/showtime/showtime"],
    pathex=[],
    binaries=[],
    datas=[("../../_build/showtime/showtime.gresource", "Resources")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={
        "gstreamer": {
            "exclude_plugins": [
                "gtk",
            ],
        },
        "gi": {
            "module-versions": {
                "Gtk": "4.0",
            },
        },
    },
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
    name="Showtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name="Showtime",
)
app = BUNDLE(
    coll,
    name="Showtime.app",
    icon="./icon.icns",
    bundle_identifier="org.gnome.Showtime",
    info_plist={
        "LSApplicationCategoryType": "public.app-category.video",
        "CFBundleDocumentTypes": [
            {
                "LSItemContentTypes": [
                    "public.movie",
                ],
                "CFBundleTypeRole": "Viewer",
            }
        ],
    },
)
