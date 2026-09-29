# PyInstaller spec: one-file windowed UniRooms.exe
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("frontend/dist", "frontend/dist")]
binaries = []
hiddenimports = collect_submodules("uvicorn") + ["multipart", "python_multipart"]
for pkg in ("ortools", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="UniRooms",
    icon="assets/icon.ico",
    console=False,
    upx=False,
)
