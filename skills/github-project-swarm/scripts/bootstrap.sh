#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd -L)"
PLUGIN_SOURCE="$SKILL_DIR/hermes-plugin"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins/github-project-swarm"
LEGACY_SHADOW="$HERMES_HOME/skills/github-project-swarm"
UNIT_DIR="$HOME/.config/systemd/user"
MARKER='managed by agent-skillfleet github-project-swarm bootstrap'

for f in "$SKILL_DIR/SKILL.md" "$SKILL_DIR/scripts/swarm_v7_cli.py" \
  "$PLUGIN_SOURCE/plugin.yaml" "$PLUGIN_SOURCE/__init__.py" \
  "$SKILL_DIR/templates/systemd/hermes-swarm-reconcile.service" \
  "$SKILL_DIR/templates/systemd/hermes-swarm-reconcile.timer"; do
  [[ -f "$f" ]] || { echo "missing github-project-swarm v7 runtime file: $f" >&2; exit 1; }
done

user_systemd=0
if systemctl --user show-environment >/dev/null 2>&1; then
  user_systemd=1
  if systemctl --user is-active --quiet hermes-swarm-reconcile.timer || \
     systemctl --user is-active --quiet hermes-swarm-reconcile.service; then
    echo "swarm reconciliation is active; run 'hermes swarm disable' before installing/updating" >&2
    exit 1
  fi
fi

atomic_copy() {
  local src="$1" dst="$2" mode="${3:-0644}" tmp
  mkdir -p "$(dirname "$dst")"
  tmp="$(mktemp "${dst}.tmp.XXXXXX")"
  cat "$src" > "$tmp"
  chmod "$mode" "$tmp"
  mv -f "$tmp" "$dst" || { rm -f "$tmp"; return 1; }
}

install_plugin() {
  local marker="$PLUGIN_DIR/.agent-skillfleet-managed" tmp
  if [[ -e "$PLUGIN_DIR" || -L "$PLUGIN_DIR" ]]; then
    [[ -d "$PLUGIN_DIR" && ! -L "$PLUGIN_DIR" ]] || {
      echo "refusing to replace non-directory Hermes swarm plugin at $PLUGIN_DIR" >&2; exit 1;
    }
    [[ -f "$marker" && "$(cat "$marker")" == "$MARKER" ]] || {
      echo "refusing to replace unmanaged Hermes swarm plugin at $PLUGIN_DIR" >&2; exit 1;
    }
  else
    mkdir -p "$PLUGIN_DIR"
  fi
  atomic_copy "$PLUGIN_SOURCE/plugin.yaml" "$PLUGIN_DIR/plugin.yaml"
  atomic_copy "$PLUGIN_SOURCE/__init__.py" "$PLUGIN_DIR/__init__.py"
  tmp="$(mktemp "${marker}.tmp.XXXXXX")"
  printf '%s\n' "$MARKER" > "$tmp"
  mv -f "$tmp" "$marker"
}

migrate_legacy_shadow() {
  local marker="$LEGACY_SHADOW/.agent-skillfleet-managed" archive_root archive
  [[ -e "$LEGACY_SHADOW" || -L "$LEGACY_SHADOW" ]] || return 0
  if [[ ! -d "$LEGACY_SHADOW" || -L "$LEGACY_SHADOW" || ! -f "$marker" || "$(cat "$marker")" != "$MARKER" ]]; then
    echo "warning: preserving unmanaged legacy swarm skill at $LEGACY_SHADOW; native resolver will ignore it" >&2
    return 0
  fi
  archive_root="$HERMES_HOME/legacy-managed-skills"
  mkdir -p "$archive_root"
  archive="$(mktemp -d "$archive_root/github-project-swarm.XXXXXX")"
  rmdir "$archive"
  mv "$LEGACY_SHADOW" "$archive"
  echo "Archived legacy managed swarm skill at $archive"
}

install_plugin
if HERMES_BIN="$(command -v hermes 2>/dev/null)"; then
  HERMES_HOME="$HERMES_HOME" "$HERMES_BIN" plugins enable github-project-swarm --no-allow-tool-override >/dev/null
  HERMES_HOME="$HERMES_HOME" "$HERMES_BIN" swarm --help >/dev/null
else
  echo "warning: hermes executable not found on PATH; plugin installed but could not be enabled/smoke-tested" >&2
fi
migrate_legacy_shadow

atomic_copy "$SKILL_DIR/templates/systemd/hermes-swarm-reconcile.service" "$UNIT_DIR/hermes-swarm-reconcile.service"
atomic_copy "$SKILL_DIR/templates/systemd/hermes-swarm-reconcile.timer" "$UNIT_DIR/hermes-swarm-reconcile.timer"
if (( user_systemd )); then
  systemctl --user daemon-reload
fi

echo "Installed native Hermes swarm v7 integration; controller remains Skillfleet runtime/current."
echo "Timer remains disabled/stopped. Next: hermes swarm validate; hermes swarm prepare; hermes swarm activate"
