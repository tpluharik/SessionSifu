#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
extension_dir="$project_dir/extension/sessionsifu@local"
dist_dir="$project_dir/dist"
package="$dist_dir/sessionsifu_1.0.0_all.deb"
stage=$(mktemp -d /tmp/sessionsifu-package.XXXXXX)
trap 'rm -rf -- "$stage"' EXIT HUP INT TERM
chmod 0755 "$stage"

python3 -m py_compile "$project_dir/app/sessionsifu"
python3 -m json.tool "$extension_dir/metadata.json" >/dev/null
desktop-file-validate "$project_dir/app/org.gnome.SessionSifu.desktop"
desktop-file-validate "$project_dir/app/org.gnome.SessionSifu.Autostart.desktop"
glib-compile-schemas --strict "$extension_dir/schemas"

find "$extension_dir" -type f -name '*.js' -exec node --check {} \;
python3 "$project_dir/tests/test_static.py" "$project_dir"

mkdir -p "$stage/DEBIAN"
mkdir -p "$stage/usr/bin"
mkdir -p "$stage/usr/share/applications"
mkdir -p "$stage/etc/xdg/autostart"
mkdir -p "$stage/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$stage/usr/share/gnome-shell/extensions/sessionsifu@local"
mkdir -p "$stage/usr/share/doc/sessionsifu"

install -m 0644 "$project_dir/packaging/control" "$stage/DEBIAN/control"
install -m 0755 "$project_dir/packaging/postinst" "$stage/DEBIAN/postinst"
install -m 0755 "$project_dir/packaging/postrm" "$stage/DEBIAN/postrm"
install -m 0755 "$project_dir/app/sessionsifu" "$stage/usr/bin/sessionsifu"
install -m 0644 "$project_dir/app/org.gnome.SessionSifu.desktop" "$stage/usr/share/applications/org.gnome.SessionSifu.desktop"
install -m 0644 "$project_dir/app/org.gnome.SessionSifu.Autostart.desktop" "$stage/etc/xdg/autostart/org.gnome.SessionSifu.desktop"
install -m 0644 "$project_dir/app/org.gnome.SessionSifu.svg" "$stage/usr/share/icons/hicolor/scalable/apps/org.gnome.SessionSifu.svg"
cp -a "$extension_dir/." "$stage/usr/share/gnome-shell/extensions/sessionsifu@local/"
find "$stage/usr/share/gnome-shell/extensions/sessionsifu@local" -type d -exec chmod 0755 {} \;
find "$stage/usr/share/gnome-shell/extensions/sessionsifu@local" -type f -exec chmod 0644 {} \;
chmod 0755 "$stage/usr/share/gnome-shell/extensions/sessionsifu@local/template/launch-app.sh"
install -m 0644 "$project_dir/README.md" "$stage/usr/share/doc/sessionsifu/README.md"
install -m 0644 "$project_dir/NOTICE" "$stage/usr/share/doc/sessionsifu/NOTICE"
install -m 0644 "$extension_dir/LICENSE" "$stage/usr/share/doc/sessionsifu/copyright"
find "$stage" -type d -exec chmod 0755 {} \;

mkdir -p "$dist_dir"
dpkg-deb --build --root-owner-group "$stage" "$package"
printf '%s\n' "$package"
