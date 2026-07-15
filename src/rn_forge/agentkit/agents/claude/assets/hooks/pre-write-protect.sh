#!/usr/bin/env bash
# agentkit:claude hooks/pre-write-protect.sh
# Blocks writes/edits to sensitive files. Requires: jq
# Exit 2 = block. Exit 0 = allow.

command -v jq &>/dev/null || { echo "BLOCKED [pre-write-protect]: jq not found — safety hook disabled. Install jq to proceed." >&2; exit 2; }

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // .tool_input.path // ""')

[ -z "$FILE" ] && exit 0

block() {
  echo "BLOCKED [pre-write-protect]: Write to '$FILE' ($1). Requires explicit user confirmation." >&2
  exit 2
}

# SSH & TLS keys
echo "$FILE" | grep -qE '(^|/)id_(rsa|ed25519|ecdsa)' && block "SSH private key"
echo "$FILE" | grep -qE '\.pem$' && block "PEM certificate/key"
echo "$FILE" | grep -qE '\.key$' && block "private key"
echo "$FILE" | grep -qE '\.p12$|\.pfx$' && block "PKCS12 keystore"
echo "$FILE" | grep -qE '\.(gpg|asc)$' && block "GPG/PGP key file"

# Cloud & infra credentials
echo "$FILE" | grep -qE 'credentials(\.json)?$' && block "credentials file"
echo "$FILE" | grep -qE 'service.?account.*\.json$' && block "service account credentials"
echo "$FILE" | grep -qE '(^|/)\.kube/config$' && block "kubeconfig (cluster credentials)"

# Package registry tokens
echo "$FILE" | grep -qE '(^|/)\.npmrc$' && block "npmrc (may contain tokens)"
echo "$FILE" | grep -qE '(^|/)\.pypirc$' && block "pypirc (may contain tokens)"
echo "$FILE" | grep -qE '(^|/)\.netrc$' && block "netrc credentials"

# Application secrets
echo "$FILE" | grep -qE '(^|/)\.env(\.|$)' && block "environment secrets"
echo "$FILE" | grep -qE '\.secrets?(/|$)' && block "secrets file/directory"

# Infrastructure state
echo "$FILE" | grep -qE '\.tfvars$' && block "Terraform variables (may contain secrets)"
echo "$FILE" | grep -qE '\.tfstate$' && block "Terraform state (contains sensitive resource data)"

# Git internals
echo "$FILE" | grep -qE '(^|/)\.git/' && block "git internal file"

exit 0
