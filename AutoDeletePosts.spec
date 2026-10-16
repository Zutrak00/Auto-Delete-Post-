# PyInstaller build recipe for the standalone app: pyinstaller AutoDeletePosts.spec
# Produces one file in dist/ that runs without Python installed.

a = Analysis(
    ["app_entry.py"],
    datas=[("autodelete/templates", "autodelete/templates")],
    hiddenimports=[],
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="AutoDeletePosts",
    console=True,  # the window shows the address and closing it stops the app
    upx=False,
)
