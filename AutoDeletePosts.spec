# PyInstaller build recipe for the standalone app: pyinstaller AutoDeletePosts.spec
# Produces one file in dist/ that runs without Python installed.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ["app_entry.py"],
    # Playwright's driver (a bundled Node.js) controls the browser for X and Instagram.
    datas=[("autodelete/templates", "autodelete/templates")] + collect_data_files("playwright"),
    hiddenimports=collect_submodules("playwright"),
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
