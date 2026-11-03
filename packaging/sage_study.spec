# PyInstaller recipe for the Tier B downloads. Build from the repo root:
#     python -m PyInstaller --noconfirm --clean packaging/sage_study.spec
# The result is dist/SageStudy/ (Windows, Linux) or dist/SageStudy.app (macOS).
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
SAGE = ROOT / "backend" / "sage"
VERSION = re.search(r'__version__ = "(.+)"', (SAGE / "__init__.py").read_text()).group(1)

datas = [(str(SAGE / folder), f"sage/{folder}") for folder in ("web", "assets", "demo")]
binaries = []
hiddenimports = ["sage.prompts", "sage.routers", "sage.schemas", "sage.services"]
# Packages that read their own data files or load parts of themselves by name at runtime.
for package in ("webview", "uvicorn", "keyring", "trafilatura", "justext", "htmldate", "courlan", "dateparser", "tld", "pptx", "docx",
                "youtube_transcript_api", "lxml", "charset_normalizer"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
if sys.platform == "win32":
    for package in ("clr_loader", "pythonnet"):
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SageStudy",
    console=False,
    icon=str(SAGE / "assets" / "icon" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")),
)
coll = COLLECT(exe, a.binaries, a.datas, name="SageStudy")
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SageStudy.app",
        icon=str(SAGE / "assets" / "icon" / "icon.icns"),
        bundle_identifier="io.github.kfcasey7.sagestudy",
        version=VERSION,
        info_plist={"CFBundleDisplayName": "Sage Study", "CFBundleName": "Sage Study", "NSHighResolutionCapable": True},
    )
