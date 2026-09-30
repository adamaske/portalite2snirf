# Standalone program for people without Python:  uv run pyinstaller packaging/portalite2snirf.spec
# Windows: one "PortaLite to SNIRF.exe". macOS: "PortaLite to SNIRF.app", which accepts dropped CSVs.
# PyInstaller cannot cross-compile, so build on the target system (see .github/workflows/release.yml).
import os
import sys
from importlib.metadata import version

from PyInstaller.utils.hooks import collect_data_files

NAME = "PortaLite to SNIRF"

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    datas=collect_data_files("portalite2snirf"),  # the 10-5 landmark file
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, exclude_binaries=True, name=NAME, console=False, argv_emulation=True, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        bundle_identifier="io.github.adamaske.portalite2snirf",
        info_plist={
            "CFBundleShortVersionString": version("portalite2snirf"),
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PortaLite CSV export",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": ["public.comma-separated-values-text"],
                "LSHandlerRank": "Alternate",
            }],
        },
    )
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name=NAME, console=False, upx=False)
