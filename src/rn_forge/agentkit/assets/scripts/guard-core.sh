#!/usr/bin/env bash
# agentkit: shared destructive-command and prompt-secret guard logic.

_guard_block() {
  printf '%s\n' "$1"
  return 1
}

guard_check_bash_command() {
  local cmd="$1"
  local rm_rf

  [ -z "$cmd" ] && return 0
  rm_rf='rm\s+(-[a-zA-Z]*[rR][a-zA-Z]*[fF]|-[a-zA-Z]*[fF][a-zA-Z]*[rR])\s+'

  if printf '%s' "$cmd" | grep -qiE "${rm_rf}/"; then
    _guard_block "Deletes entire filesystem"
    return 1
  fi
  if printf '%s' "$cmd" | grep -qiE "${rm_rf}~"; then
    _guard_block "Deletes home directory"
    return 1
  fi
  if printf '%s' "$cmd" | grep -qE "${rm_rf}[\"']?\\\$HOME"; then
    _guard_block "Deletes home directory"
    return 1
  fi
  if printf '%s' "$cmd" | grep -qiE "${rm_rf}\*"; then
    _guard_block "Wildcard recursive delete"
    return 1
  fi
  if printf '%s' "$cmd" | grep -qiE "${rm_rf}\."; then
    _guard_block "Deletes current directory"
    return 1
  fi

  if printf '%s' "$cmd" | grep -qE '\bgit\s+push\b'; then
    _guard_check_git_push "$cmd" || return 1
  fi

  _guard_match_bash "$cmd" 'git\s+reset\s+--hard' "Discards all uncommitted changes" || return 1
  _guard_match_bash "$cmd" 'git\s+clean\s+-[a-z]*f' "Permanently deletes untracked files" || return 1
  _guard_match_bash "$cmd" 'git\s+checkout\s+--\s+\.' "Discards all working directory changes" || return 1
  _guard_match_bash "$cmd" '(psql|mysql|sqlite3|mongosh)\b.*\b(DROP\s+(TABLE|DATABASE)|TRUNCATE)\b' "Destructive database operation" || return 1
  _guard_match_bash "$cmd" '>\s*/dev/sd' "Direct disk write" || return 1
  _guard_match_bash "$cmd" '\bmkfs\b' "Formats filesystem" || return 1
  _guard_match_bash "$cmd" 'chmod\s+-R\s+777' "Insecure recursive permission change" || return 1
  _guard_match_bash "$cmd" '(curl|wget)\b.*\|\s*(ba)?sh\b' "Remote script execution" || return 1
  if printf '%s' "$cmd" | grep -qF '(){:|:&};:'; then
    _guard_block "Fork bomb detected"
    return 1
  fi
  return 0
}

_guard_check_git_push() {
  local cmd="$1"
  local protected push_args token branch ref skip_next
  local -a args positionals

  protected="${AGENTKIT_PROTECTED_BRANCHES:-${CLAUDE_PROTECTED_BRANCHES:-main|master}}"
  push_args=$(printf '%s' "$cmd" | sed -E 's/^.*git[[:space:]]+push([[:space:]]+|$)//')
  read -r -a args <<<"$push_args"

  for token in "${args[@]}"; do
    token=$(_guard_clean_push_token "$token")
    case "$token" in
      --force | -f)
        _guard_block "Force push rewrites remote history"
        return 1
        ;;
    esac
  done

  skip_next=false
  for token in "${args[@]}"; do
    token=$(_guard_clean_push_token "$token")
    if [ "$skip_next" = true ]; then
      skip_next=false
      continue
    fi
    case "$token" in
      ';' | '&&' | '||' | '|') break ;;
      --repo | --receive-pack | --exec | --push-option | -o)
        skip_next=true
        ;;
      --repo=* | --receive-pack=* | --exec=* | --push-option=* | -o*) ;;
      --) ;;
      -*) ;;
      '') ;;
      *) positionals+=("$token") ;;
    esac
  done

  branch=$(git branch --show-current 2>/dev/null || true)
  if [ "${#positionals[@]}" -le 1 ]; then
    if _guard_ref_is_protected "$branch" "$protected"; then
      _guard_block "Push from protected branch '$branch'"
      return 1
    fi
    return 0
  fi

  for ref in "${positionals[@]:1}"; do
    if [ "$ref" = "HEAD" ]; then
      ref="$branch"
    elif [[ "$ref" == *:* ]]; then
      ref="${ref#*:}"
    fi
    ref="${ref#+}"
    ref="${ref#refs/heads/}"
    if _guard_ref_is_protected "$ref" "$protected"; then
      _guard_block "Push to protected branch"
      return 1
    fi
  done
  return 0
}

_guard_clean_push_token() {
  local token="$1"
  token="${token#\"}"
  token="${token#\'}"
  token="${token%\"}"
  token="${token%\'}"
  token="${token%;}"
  printf '%s' "$token"
}

_guard_ref_is_protected() {
  local ref="$1" protected="$2"
  [ -n "$ref" ] && printf '%s' "$ref" | grep -qE "^(${protected})$"
}

_guard_match_bash() {
  local value="$1" pattern="$2" reason="$3"
  if printf '%s' "$value" | grep -qiE -- "$pattern"; then
    _guard_block "$reason"
    return 1
  fi
  return 0
}

guard_check_write_path() {
  local path="$1"

  [ -z "$path" ] && return 0
  _guard_match_path "$path" '(^|/)id_(rsa|ed25519|ecdsa)' "SSH private key" || return 1
  _guard_match_path "$path" '\.pem$' "PEM certificate/key" || return 1
  _guard_match_path "$path" '\.key$' "private key" || return 1
  _guard_match_path "$path" '\.(p12|pfx)$' "PKCS12 keystore" || return 1
  _guard_match_path "$path" '\.(gpg|asc)$' "GPG/PGP key file" || return 1
  _guard_match_path "$path" 'credentials(\.json)?$' "credentials file" || return 1
  _guard_match_path "$path" 'service.?account.*\.json$' "service account credentials" || return 1
  _guard_match_path "$path" '(^|/)\.kube/config$' "kubeconfig (cluster credentials)" || return 1
  _guard_match_path "$path" '(^|/)\.npmrc$' "npmrc (may contain tokens)" || return 1
  _guard_match_path "$path" '(^|/)\.pypirc$' "pypirc (may contain tokens)" || return 1
  _guard_match_path "$path" '(^|/)\.netrc$' "netrc credentials" || return 1
  _guard_match_path "$path" '(^|/)\.env(\.|$)' "environment secrets" || return 1
  _guard_match_path "$path" '\.secrets?(/|$)' "secrets file/directory" || return 1
  _guard_match_path "$path" '\.tfvars$' "Terraform variables (may contain secrets)" || return 1
  _guard_match_path "$path" '\.tfstate$' "Terraform state (contains sensitive resource data)" || return 1
  _guard_match_path "$path" '(^|/)\.git/' "git internal file" || return 1
  return 0
}

_guard_match_path() {
  local value="$1" pattern="$2" reason="$3"
  if printf '%s' "$value" | grep -qE -- "$pattern"; then
    _guard_block "$reason"
    return 1
  fi
  return 0
}

guard_check_prompt_secrets() {
  local prompt="$1"
  local gitleaks_output

  [ -z "$prompt" ] && return 0
  if command -v gitleaks >/dev/null 2>&1; then
    if ! gitleaks_output=$(printf '%s' "$prompt" | gitleaks stdin 2>&1); then
      if printf '%s' "$gitleaks_output" | grep -qE 'leaks found: [1-9][0-9]*'; then
        _guard_block "Prompt contains a secret detected by gitleaks. Remove secrets before sending."
      else
        _guard_block "Prompt secret scan failed because gitleaks could not run. Fix gitleaks before sending."
      fi
      return 1
    fi
  fi
  _guard_match_secret "$prompt" '\bsk-[A-Za-z0-9_-]{16,}\b' "Prompt contains an OpenAI-style API key. Remove secrets before sending." || return 1
  _guard_match_secret "$prompt" '\bgh[pousr]_[A-Za-z0-9]{20,}\b' "Prompt contains a GitHub token. Remove secrets before sending." || return 1
  _guard_match_secret "$prompt" '\bgithub_pat_[A-Za-z0-9_]{20,}\b' "Prompt contains a GitHub personal access token. Remove secrets before sending." || return 1
  _guard_match_secret "$prompt" '\bsk-ant-[A-Za-z0-9_-]{16,}\b' "Prompt contains an Anthropic API key. Remove secrets before sending." || return 1
  _guard_match_secret "$prompt" '-----BEGIN (RSA |EC |OPENSSH |)?PRIVATE KEY-----' "Prompt contains a private key. Remove secrets before sending." || return 1
  _guard_match_secret "$prompt" 'AKIA[0-9A-Z]{16}' "Prompt contains an AWS access key. Remove secrets before sending." || return 1
  _guard_match_secret "$prompt" '\bxox[baprs]-[A-Za-z0-9-]{10,}\b' "Prompt contains a Slack token. Remove secrets before sending." || return 1
  _guard_match_secret "$prompt" '\bglpat-[A-Za-z0-9_-]{20,}\b' "Prompt contains a GitLab token. Remove secrets before sending." || return 1
  _guard_match_secret "$prompt" '\b(OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|ANTHROPIC_API_KEY|AWS_SECRET_ACCESS_KEY)\s*=\s*[^[:space:]]+' "Prompt contains an assigned secret value. Remove secrets before sending." || return 1
  return 0
}

_guard_match_secret() {
  local value="$1" pattern="$2" reason="$3"
  if printf '%s' "$value" | grep -qE -- "$pattern"; then
    _guard_block "$reason"
    return 1
  fi
  return 0
}

# ============================================================
# EMIT: Claude dialect — plain text to stderr, exit code signals outcome.
# ============================================================

guard_require_jq_plain() {
  local hook="$1" mode="$2"
  command -v jq >/dev/null 2>&1 && return 0
  if [ "$mode" = "warn" ]; then
    echo "WARNING [$hook]: jq not found — prompt secret scan skipped. Install jq." >&2
    exit 1
  fi
  echo "BLOCKED [$hook]: jq not found — safety hook cannot run. Install jq to proceed." >&2
  exit 2
}

guard_emit_plain() {
  local hook="$1" message="$2" code="$3"
  if [ "$code" = "1" ]; then
    echo "WARNING [$hook]: $message" >&2
  else
    echo "BLOCKED [$hook]: $message" >&2
  fi
  exit "$code"
}

# ============================================================
# EMIT: Codex dialect — JSON decision on stdout, always exits 0.
# ============================================================

guard_require_jq_json() {
  local hook="$1" mode="$2"
  command -v jq >/dev/null 2>&1 && return 0
  if [ "$mode" = "warn" ]; then
    echo "WARNING [$hook]: jq not found — prompt secret scan skipped. Install jq." >&2
    exit 0
  fi
  printf '{"decision":"block","reason":"jq not found; safety hook cannot run"}\n'
  exit 0
}

guard_emit_json_block() {
  local reason="$1"
  jq -cn --arg reason "$reason" '{decision:"block",reason:$reason}'
  exit 0
}
