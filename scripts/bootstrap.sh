#!/usr/bin/env bash
# Install agentkit on a new machine without a manual git clone: fetches the
# source tarball for the latest GitHub release and runs install.sh from it.
#
#   curl -fsSL https://raw.githubusercontent.com/rn-forge/agentkit/main/scripts/bootstrap.sh | bash
#
# Requires: curl, tar, uv (https://docs.astral.sh/uv/). Honors RNF_HOME the
# same way install.sh does.

set -euo pipefail

# Check every prerequisite up front. Failing on the first missing tool halfway
# through a download leaves a confusing partial state and a worse error.
missing=""
for tool in curl tar uv; do
  command -v "${tool}" >/dev/null 2>&1 || missing="${missing} ${tool}"
done
if [ -n "${missing}" ]; then
  echo "bootstrap.sh: missing required tool(s):${missing}" >&2
  echo "  install them first — see https://rn-forge.github.io/agentkit/guides/development/#external-dependencies" >&2
  exit 1
fi

repo="rn-forge/agentkit"
work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

echo "Resolving latest agentkit release..."
tag="$(curl -fsSL "https://api.github.com/repos/${repo}/releases/latest" \
  | grep -m1 '"tag_name"' \
  | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
if [ -z "${tag}" ]; then
  echo "bootstrap.sh: could not resolve latest release tag for ${repo}" >&2
  exit 1
fi

echo "Downloading ${repo}@${tag} source..."
curl -fsSL "https://github.com/${repo}/archive/refs/tags/${tag}.tar.gz" \
  | tar -xz -C "${work_dir}"

src_dir="$(find "${work_dir}" -maxdepth 1 -mindepth 1 -type d | head -n 1)"
if [ -z "${src_dir}" ]; then
  echo "bootstrap.sh: extracted archive was empty" >&2
  exit 1
fi

"${src_dir}/install.sh"
