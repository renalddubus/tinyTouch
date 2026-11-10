#!/bin/sh
# tinyTouch installer for macOS.
set -eu

release_root="${TINYTOUCH_RELEASE_ROOT:-https://github.com/ZimengXiong/tinyTouch/releases/latest/download}"
# Release builds replace the placeholder with the Apple Team ID that signs the
# CLI. A source checkout is unstamped and must be given TINYTOUCH_EXPECTED_TEAM_ID.
pinned_team_id='__TINYTOUCH_TEAM_ID__'
case "$pinned_team_id" in
  __*)
    pinned_team_id="${TINYTOUCH_EXPECTED_TEAM_ID:-}"
    codesign_tool=codesign
    ;;
  *)
    codesign_tool=/usr/bin/codesign
    ;;
esac
case "$pinned_team_id" in
  *[!A-Z0-9]*|'')
    echo 'This installer has no pinned signing team. Use the official release installer.' >&2
    exit 1
    ;;
esac
if [ "${#pinned_team_id}" -ne 10 ]; then
  echo 'This installer has an invalid signing team.' >&2
  exit 1
fi
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM

if [ "$(uname -s)" != 'Darwin' ]; then
  echo 'tinyTouch setup requires macOS.' >&2
  exit 1
fi

machine="$(uname -m)"
if [ "$machine" = 'x86_64' ] && [ "$(/usr/sbin/sysctl -in sysctl.proc_translated 2>/dev/null || true)" = '1' ]; then
  machine='arm64'
fi
case "$machine" in
  arm64) cli_key='macos-arm64'; expected_file='tinytouch-macos-arm64.tar.gz' ;;
  x86_64) cli_key='macos-x86_64'; expected_file='tinytouch-macos-x86_64.tar.gz' ;;
  *) echo "tinyTouch does not support this Mac architecture: $(uname -m)." >&2; exit 1 ;;
esac

curl -fsSL "$release_root/release-manifest.json" -o "$work_dir/release.json"
version="$(plutil -extract version raw -o - "$work_dir/release.json")"
release_file="$(plutil -extract "cli.$cli_key.file" raw -o - "$work_dir/release.json")"
release_sha256="$(plutil -extract "cli.$cli_key.sha256" raw -o - "$work_dir/release.json")"
case "$version" in
  [0-9]*.[0-9]*.[0-9]*|[0-9]*.[0-9]*.[0-9]*-*) ;;
  *) echo 'The tinyTouch release version is not valid.' >&2; exit 1 ;;
esac
if [ "$release_file" != "$expected_file" ]; then
  echo 'The tinyTouch CLI filename is not valid.' >&2
  exit 1
fi
case "$release_sha256" in
  *[!0-9a-f]*|'') echo 'The tinyTouch CLI checksum is not valid.' >&2; exit 1 ;;
esac
if [ "${#release_sha256}" -ne 64 ]; then
  echo 'The tinyTouch CLI checksum is not valid.' >&2
  exit 1
fi
release_url="$release_root/$release_file"

# The checksum only detects a damaged download: the manifest comes from the same
# place as the archive. Trust comes from the pinned Apple Team ID, which an
# attacker who can replace release files cannot forge.
verify_signed_by_team() {
  requirement="anchor apple generic and certificate leaf[subject.OU] = \"$pinned_team_id\""
  "$codesign_tool" --verify --strict -R "=$requirement" "$1" >/dev/null 2>&1
}

verify_cli_bundle() {
  cli_dir="$1"
  newline='
'
  if [ -n "$(find "$cli_dir" -name "*$newline*" -print -quit)" ]; then
    return 1
  fi
  "$codesign_tool" --verify --strict \
    -R "=identifier \"com.tinytouch.cli\" and anchor apple generic and certificate leaf[subject.OU] = \"$pinned_team_id\"" \
    "$cli_dir/tinytouch" >/dev/null 2>&1 || return 1
  "$codesign_tool" -d --verbose=2 "$cli_dir/tinytouch" 2>&1 | grep -q 'flags=.*runtime' || return 1
  find "$cli_dir/_internal" -type f ! -type l > "$work_dir/library-list"
  while IFS= read -r library; do
    if file -b "$library" | grep -q 'Mach-O'; then
      verify_signed_by_team "$library" || return 1
    fi
  done < "$work_dir/library-list"
}

path_contains() {
  case ":$PATH:" in
    *":$1:"*) return 0 ;;
    *) return 1 ;;
  esac
}

if [ -n "${TINYTOUCH_INSTALL_DIR:-${TINTOUCH_INSTALL_DIR:-}}" ]; then
  install_dir="${TINYTOUCH_INSTALL_DIR:-$TINTOUCH_INSTALL_DIR}"
elif existing_command="$(command -v tinytouch 2>/dev/null)"; then
  case "$existing_command" in
    "$HOME/.local/bin/tinytouch"|/opt/homebrew/bin/tinytouch|/usr/local/bin/tinytouch)
      install_dir="${existing_command%/tinytouch}"
      ;;
    *) existing_command='' ;;
  esac
fi

if [ -z "${install_dir:-}" ]; then
  for candidate in "$HOME/.local/bin" /opt/homebrew/bin /usr/local/bin; do
    if path_contains "$candidate"; then
      install_dir="$candidate"
      break
    fi
  done
fi

if [ -z "${install_dir:-}" ]; then
  echo "No supported install directory is on this terminal's PATH." >&2
  echo 'Set TINYTOUCH_INSTALL_DIR to a directory already on PATH. Then run the installer again.' >&2
  exit 1
fi

echo 'Installing tinyTouch...'
curl -fsSL "$release_url" -o "$work_dir/tinytouch.tar.gz"
actual_sha256="$(shasum -a 256 "$work_dir/tinytouch.tar.gz" | awk '{print $1}')"
if [ "$actual_sha256" != "$release_sha256" ]; then
  echo 'The download checksum did not match. Installation stopped.' >&2
  echo 'Contact tinytouch@alpacaengineer.ing if this continues.' >&2
  exit 1
fi

tar -C "$work_dir" -xzf "$work_dir/tinytouch.tar.gz"
test -x "$work_dir/tinytouch/tinytouch"
test -d "$work_dir/tinytouch/_internal"
support_dir="$HOME/Library/Application Support/tinyTouch"
bundle="$support_dir/cli-$(printf %.16s "$release_sha256")"
mkdir -p "$support_dir"
if [ ! -d "$bundle" ]; then
  mv "$work_dir/tinytouch" "$bundle"
fi

# Never run anything from the download before its signature matches the team.
if ! verify_cli_bundle "$bundle"; then
  echo 'The tinyTouch CLI is not signed by the expected developer. Installation stopped.' >&2
  echo 'Contact tinytouch@alpacaengineer.ing if this continues.' >&2
  rm -rf "$bundle"
  exit 1
fi

if ! "$bundle/tinytouch" --version; then
  echo 'The downloaded tinyTouch CLI cannot start on this Mac.' >&2
  echo 'Installation stopped. Contact tinytouch@alpacaengineer.ing.' >&2
  exit 1
fi

# Keep the current CLI and helper until credential access has been verified.
if ! "$bundle/tinytouch" _upgrade-helper; then
  echo 'HID service upgrade did not finish. The CLI command was not replaced.' >&2
  exit 1
fi

if { [ -d "$install_dir" ] && [ -w "$install_dir" ]; } || \
   { [ ! -e "$install_dir" ] && [ -w "${install_dir%/*}" ]; }; then
  mkdir -p "$install_dir"
  ln -sfn "$bundle/tinytouch" "$install_dir/.tinytouch.new"
  mv -f "$install_dir/.tinytouch.new" "$install_dir/tinytouch"
else
  echo "Installation in $install_dir requires your Mac administrator password."
  sudo mkdir -p "$install_dir"
  sudo ln -sfn "$bundle/tinytouch" "$install_dir/.tinytouch.new"
  sudo mv -f "$install_dir/.tinytouch.new" "$install_dir/tinytouch"
fi

echo 'tinyTouch installed. Run: tinytouch setup'
