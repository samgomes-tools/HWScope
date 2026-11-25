#!/bin/bash
# Gera HWScope-x86_64.AppImage.
# Requer: curl, squashfs-tools (unsquashfs/mksquashfs), python3 + pip, binutils (readelf), dpkg-deb.
# Uso: ./build.sh            -> usa a versão definida em ui/meta.py
#      VERSION=0.9.3 ./build.sh -> grava essa versão no app antes de empacotar
set -euo pipefail
cd "$(dirname "$0")"
SRC=$PWD; W=$SRC/_build; rm -rf "$W"; mkdir -p "$W"; cd "$W"
PY=python3.12.15-cp312-cp312-manylinux2014_x86_64.AppImage
curl -fsSL -o py.AppImage https://github.com/niess/python-appimage/releases/download/python3.12/$PY
curl -fsSL -o runtime https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64
OFF=$(python3 -c "import struct,sys;d=open('py.AppImage','rb').read(64);o=struct.unpack_from('<Q',d,0x28)[0];a,b=struct.unpack_from('<HH',d,0x3A);print(o+a*b)")
unsquashfs -q -o "$OFF" -d AppDir py.AppImage
SP=AppDir/opt/python3.12/lib/python3.12/site-packages
python3 -m pip install -q --target $SP --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
    --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: "PySide6-Essentials==6.9.3" "psutil>=5.9"
python3 "$SRC/tools/trim_pyside.py" $SP/PySide6
rm -rf $SP/pip* $SP/bin AppDir/usr/share/tcltk AppDir/*.desktop AppDir/python.png \
       AppDir/usr/share/applications AppDir/usr/share/metainfo AppDir/AppRun
# libs xcb usadas pelo Qt que faltam em instalações mínimas (versões com glibc antiga)
mkdir -p debs AppDir/usr/lib/hwscope-qt && cd debs
U=http://archive.ubuntu.com/ubuntu/pool
for p in universe/x/xcb-util-cursor/libxcb-cursor0_0.1.1-4ubuntu1 main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1build2 \
         main/x/xcb-util-image/libxcb-image0_0.4.0-2build1 main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build3 \
         main/x/xcb-util-renderutil/libxcb-render-util0_0.3.9-1build3 main/x/xcb-util/libxcb-util1_0.4.0-1build2 \
         main/libx/libxkbcommon/libxkbcommon-x11-0_1.4.0-1; do
  curl -fsSL -o p.deb "$U/${p}_amd64.deb"; dpkg-deb -x p.deb x
done
cp -L x/usr/lib/x86_64-linux-gnu/lib*.so.[0-9] ../AppDir/usr/lib/hwscope-qt/; cd ..
A=AppDir; mkdir -p $A/opt/hwscope $A/usr/share/applications $A/usr/share/icons/hicolor/256x256/apps $A/usr/share/icons/hicolor/scalable/apps
cp -r "$SRC"/main.py "$SRC"/core "$SRC"/ui "$SRC"/data "$SRC"/hwscope.png $A/opt/hwscope/
find $A/opt/hwscope -name __pycache__ -type d -prune -exec rm -rf {} +
if [ -n "${VERSION:-}" ]; then
  sed -i "s/^APP_VERSION = .*/APP_VERSION = \"${VERSION}\"/" $A/opt/hwscope/ui/meta.py
fi
cp "$SRC"/hwscope.png $A/; cp "$SRC"/hwscope.png $A/usr/share/icons/hicolor/256x256/apps/; ln -sf hwscope.png $A/.DirIcon
cp "$SRC"/hwscope.svg $A/usr/share/icons/hicolor/scalable/apps/
rm -f $A/usr/share/icons/hicolor/256x256/apps/python.png
cp "$SRC"/packaging/hwscope.desktop $A/; cp "$SRC"/packaging/hwscope.desktop $A/usr/share/applications/
install -m755 "$SRC"/packaging/AppRun $A/AppRun
mksquashfs AppDir app.squashfs -root-owned -noappend -comp zstd -Xcompression-level 19 -b 1M -quiet
cat runtime app.squashfs > "$SRC/HWScope-x86_64.AppImage"; chmod +x "$SRC/HWScope-x86_64.AppImage"
echo "Pronto: $SRC/HWScope-x86_64.AppImage"
