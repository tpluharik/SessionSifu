#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
extension_dir="$project_dir/extension/sessionsifu@local"
dist_dir="$project_dir/dist"
updates_dir="$project_dir/updates"
version="1.2.1"
package="$dist_dir/sessionsifu_${version}_all.deb"
update_package="$updates_dir/sessionsifu_${version}_all.deb"
stage=$(mktemp -d /tmp/sessionsifu-package.XXXXXX)
trap 'rm -rf -- "$stage"' EXIT HUP INT TERM
chmod 0755 "$stage"

python3 -m py_compile "$project_dir/app/sessionsifu"
python3 -m json.tool "$extension_dir/metadata.json" >/dev/null
desktop-file-validate "$project_dir/app/org.gnome.SessionSifu.desktop"
desktop-file-validate "$project_dir/app/org.gnome.SessionSifu.Autostart.desktop"
glib-compile-schemas --strict "$extension_dir/schemas"
GSETTINGS_BACKEND=memory SESSIONSIFU_SCHEMA_DIR="$extension_dir/schemas" \
    python3 "$project_dir/tests/test_settings.py" "$project_dir"

find "$extension_dir" -type f -name '*.js' -exec node --check {} \;
gjs -m "$project_dir/tests/open-files-smoke.js"
python3 "$project_dir/tests/test_static.py" "$project_dir"

mkdir -p "$stage/DEBIAN"
mkdir -p "$stage/usr/bin"
mkdir -p "$stage/usr/share/applications"
mkdir -p "$stage/etc/xdg/autostart"
mkdir -p "$stage/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$stage/usr/share/gnome-shell/extensions/sessionsifu@local"
mkdir -p "$stage/usr/share/glib-2.0/schemas"
mkdir -p "$stage/usr/share/sessionsifu"
mkdir -p "$stage/usr/share/doc/sessionsifu"
mkdir -p "$stage/usr/share/doc/sessionsifu/docs"

install -m 0644 "$project_dir/packaging/control" "$stage/DEBIAN/control"
install -m 0755 "$project_dir/packaging/postinst" "$stage/DEBIAN/postinst"
install -m 0755 "$project_dir/packaging/postrm" "$stage/DEBIAN/postrm"
install -m 0755 "$project_dir/app/sessionsifu" "$stage/usr/bin/sessionsifu"
install -m 0644 "$project_dir/app/org.gnome.SessionSifu.desktop" "$stage/usr/share/applications/org.gnome.SessionSifu.desktop"
install -m 0644 "$project_dir/app/org.gnome.SessionSifu.Autostart.desktop" "$stage/etc/xdg/autostart/org.gnome.SessionSifu.desktop"
install -m 0644 "$project_dir/app/org.gnome.SessionSifu.svg" "$stage/usr/share/icons/hicolor/scalable/apps/org.gnome.SessionSifu.svg"
install -m 0644 "$extension_dir/schemas/org.gnome.shell.extensions.sessionsifu.gschema.xml" "$stage/usr/share/glib-2.0/schemas/org.gnome.shell.extensions.sessionsifu.gschema.xml"
cp -a "$extension_dir/." "$stage/usr/share/gnome-shell/extensions/sessionsifu@local/"
(cd "$extension_dir" && zip -qr "$stage/usr/share/sessionsifu/sessionsifu@local.shell-extension.zip" .)
chmod 0644 "$stage/usr/share/sessionsifu/sessionsifu@local.shell-extension.zip"
find "$stage/usr/share/gnome-shell/extensions/sessionsifu@local" -type d -exec chmod 0755 {} \;
find "$stage/usr/share/gnome-shell/extensions/sessionsifu@local" -type f -exec chmod 0644 {} \;
chmod 0755 "$stage/usr/share/gnome-shell/extensions/sessionsifu@local/template/launch-app.sh"
install -m 0644 "$project_dir/README.md" "$stage/usr/share/doc/sessionsifu/README.md"
install -m 0644 "$project_dir/CHANGELOG.md" "$stage/usr/share/doc/sessionsifu/CHANGELOG.md"
install -m 0644 "$project_dir/CONTRIBUTING.md" "$stage/usr/share/doc/sessionsifu/CONTRIBUTING.md"
install -m 0644 "$project_dir/docs/ARCHITECTURE.md" "$stage/usr/share/doc/sessionsifu/docs/ARCHITECTURE.md"
install -m 0644 "$project_dir/docs/TROUBLESHOOTING.md" "$stage/usr/share/doc/sessionsifu/docs/TROUBLESHOOTING.md"
install -m 0644 "$project_dir/NOTICE" "$stage/usr/share/doc/sessionsifu/NOTICE"
install -m 0644 "$extension_dir/LICENSE" "$stage/usr/share/doc/sessionsifu/copyright"
find "$stage" -type d -exec chmod 0755 {} \;

mkdir -p "$dist_dir"
dpkg-deb --build --root-owner-group "$stage" "$package"
mkdir -p "$updates_dir"
install -m 0644 "$package" "$update_package"
update_sha=$(sha256sum "$update_package" | cut -d ' ' -f 1)
update_size=$(stat -c %s "$update_package")
sed \
    -e "s/@VERSION@/$version/g" \
    -e "s/@SHA256@/$update_sha/g" \
    -e "s/@SIZE@/$update_size/g" \
    "$project_dir/packaging/latest.json.in" > "$updates_dir/latest.json"
printf '%s\n' "$package"
printf '%s\n' "$updates_dir/latest.json"
