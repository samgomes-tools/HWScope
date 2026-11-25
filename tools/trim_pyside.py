"""Remove partes do PySide6 que o HWScope não usa, preservando o fecho de dependências."""
import glob
import os
import shutil
import subprocess
import sys

PS = sys.argv[1]
Q = os.path.join(PS, "Qt")
KEEP_MODULES = {"QtCore", "QtGui", "QtWidgets", "QtDBus", "QtSvg"}
DROP_PLUGINS = {"designer", "qmllint", "qmltooling", "sqldrivers", "printsupport",
                "networkinformation", "wayland-graphics-integration-server", "tls"}

for f in os.listdir(PS):
    p = os.path.join(PS, f)
    if f.endswith(".abi3.so") and f.split(".")[0] not in KEEP_MODULES:
        os.remove(p)
    elif f.endswith(".pyi") or f in ("typesystems", "include", "glue", "scripts", "assistant",
                                      "designer", "linguist", "lrelease", "lupdate", "qmlformat",
                                      "qmlls", "qmllint", "metatypes", "py.typed", "doc"):
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    elif os.path.isfile(p) and os.access(p, os.X_OK) and not f.endswith(".so") and "." not in f:
        os.remove(p)

for d in ("qml", "metatypes", "libexec"):
    shutil.rmtree(os.path.join(Q, d), ignore_errors=True)
for f in glob.glob(os.path.join(Q, "translations", "*")):
    b = os.path.basename(f)
    if not (b.startswith("qtbase_pt") or b.startswith("qt_pt")):
        shutil.rmtree(f) if os.path.isdir(f) else os.remove(f)
for d in DROP_PLUGINS:
    shutil.rmtree(os.path.join(Q, "plugins", d), ignore_errors=True)


def needed(path):
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return [l.split("[")[1].split("]")[0] for l in out.splitlines() if "(NEEDED)" in l]


libdir = os.path.join(Q, "lib")
available = set(os.listdir(libdir))
roots = [p for p in glob.glob(os.path.join(PS, "*.so"))] + \
        glob.glob(os.path.join(Q, "plugins", "**", "*.so"), recursive=True) + \
        glob.glob(os.path.join(PS, "..", "shiboken6", "*.so"))
keep, todo = set(), []
for r in roots:
    todo += needed(r)
while todo:
    n = todo.pop()
    if n in available and n not in keep:
        keep.add(n)
        todo += needed(os.path.join(libdir, n))
removed = 0
for f in available:
    if f not in keep and f.endswith((".so", ".so.6")) or (f not in keep and ".so." in f):
        os.remove(os.path.join(libdir, f))
        removed += 1
print("libs mantidas:", sorted(keep))
print("removidas:", removed)
