#!/usr/bin/env bash
# Install agentkit from this checkout into the rn-forge versioned layout.

_agentkit_sourced=0
if [ -n "${BASH_VERSION:-}" ] && [ "${BASH_SOURCE[0]}" != "$0" ]; then
  _agentkit_sourced=1
fi
if [ -n "${ZSH_VERSION:-}" ]; then
  case "${ZSH_EVAL_CONTEXT:-}" in
    *:file) _agentkit_sourced=1 ;;
  esac
  # zsh (unlike bash) already updates $0 to the sourced file's path.
  _agentkit_script_path="$0"
else
  _agentkit_script_path="${BASH_SOURCE[0]:-$0}"
fi

# Serialize concurrent installs/upgrades via a portable mkdir-based lock (no
# flock assumption). Released by a trap: this function always runs in a
# standalone or sourced *top-level* shell, never inside a caller's own trap.
_agentkit_acquire_install_lock() {
  local lock_dir="$1" waited=0
  while ! mkdir "${lock_dir}" 2>/dev/null; do
    if [ "${waited}" -eq 0 ]; then
      echo "install.sh: waiting for install lock ${lock_dir} (held by another install) ..."
    fi
    if [ "${waited}" -ge 30 ]; then
      echo "install.sh: could not acquire install lock ${lock_dir}" >&2
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  trap 'rm -rf "${lock_dir}"' EXIT
}

agentkit_install() {
  local script_path repo_root version rnf_home product_home target scratch
  local current_resolved target_resolved

  script_path="${_agentkit_script_path}"
  repo_root="$(cd "$(dirname "${script_path}")" && pwd -P)" || return 1
  rnf_home="${RNF_HOME:-${HOME}/.rn-forge}"
  version="$(grep '^version' "${repo_root}/pyproject.toml" | head -n 1 | cut -d '"' -f 2)"
  if [ -z "${version}" ]; then
    echo "install.sh: could not read version from ${repo_root}/pyproject.toml" >&2
    return 1
  fi

  product_home="${rnf_home}/agentkit"
  target="${product_home}/v${version}"
  current_resolved="$(cd "${product_home}/current" 2>/dev/null && pwd -P || true)"
  target_resolved="$(cd "${target}" 2>/dev/null && pwd -P || true)"
  if [ -n "${target_resolved}" ] \
    && [ "${current_resolved}" = "${target_resolved}" ] \
    && [ -e "${rnf_home}/bin/agentkit" ]; then
    echo "agentkit v${version} is already installed (${product_home}/current)."
    return 0
  fi

  if ! command -v uv >/dev/null 2>&1; then
    echo "install.sh: uv is required but was not found on PATH." >&2
    echo "  install it from https://docs.astral.sh/uv/getting-started/installation/" >&2
    return 1
  fi

  echo "Installing agentkit v${version} into ${target} ..."
  mkdir -p "${product_home}" || return 1
  _agentkit_acquire_install_lock "${product_home}/.install.lock" || return 1

  # `target` is this version's own directory, distinct from whatever
  # `current` points to today, so nothing observes it mid-build; the lock
  # only needs to prevent two installs racing on the same target. What must
  # be atomic is the `current` flip itself: build a new symlink under a
  # private name and rename it over `current` in one syscall, rather than
  # `ln -sfn`'s remove-then-recreate.
  (
    cd "${repo_root}" || exit 1
    UV_PROJECT_ENVIRONMENT="${target}" uv sync --frozen --no-dev --no-editable
  ) || return 1

  scratch="${product_home}/.current.tmp.$$"
  rm -f "${scratch}"
  ln -s "v${version}" "${scratch}" || return 1
  mv -f "${scratch}" "${product_home}/current" || return 1
  rm -rf "${product_home}/.install.lock"
  trap - EXIT

  mkdir -p "${rnf_home}/bin" || return 1
  ln -sfn "../agentkit/current/bin/agentkit" "${rnf_home}/bin/agentkit" || return 1

  echo "agentkit v${version} installed. next steps:"
  echo "  export PATH=\"${rnf_home}/bin:\${PATH}\"   # add to your shell profile to persist"
  echo "  agentkit global apply"
}

if [ "${_agentkit_sourced}" -eq 1 ]; then
  agentkit_install
  _agentkit_status=$?
  unset -f agentkit_install
  unset _agentkit_sourced _agentkit_script_path
  if [ "${_agentkit_status}" -eq 0 ]; then
    unset _agentkit_status
    return 0
  fi
  unset _agentkit_status
  return 1
fi

set -euo pipefail
agentkit_install
unset -f agentkit_install
unset _agentkit_sourced _agentkit_script_path
