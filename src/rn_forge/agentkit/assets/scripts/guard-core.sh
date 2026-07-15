#!/usr/bin/env bash
# agentkit: shared destructive-command and prompt-secret guard logic.

_guard_block() {
  printf '%s\n' "$1"
  return 1
}

guard_check_bash_command() {
  local cmd="$1"
  local rm_rf protected branch

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

  _guard_match_bash "$cmd" 'git\s+push\s+(--force|-f)' "Force push rewrites remote history" || return 1

  protected="${CLAUDE_PROTECTED_BRANCHES:-main|master}"
  if printf '%s' "$cmd" | grep -qE '\bgit\s+push\b'; then
    if printf '%s' "$cmd" | grep -qE "git\s+push\s.*(\s|:)(${protected})\b"; then
      _guard_block "Push to protected branch"
      return 1
    fi
    if ! printf '%s' "$cmd" | grep -qE 'git\s+push\s+[^-][^ ]*\s+\S+'; then
      branch=$(git branch --show-current 2>/dev/null || true)
      if printf '%s' "$branch" | grep -qE "^(${protected})$"; then
        _guard_block "Push from protected branch '$branch'"
        return 1
      fi
    fi
  fi

  _guard_match_bash "$cmd" 'git\s+reset\s+--hard' "Discards all uncommitted changes" || return 1
  _guard_match_bash "$cmd" 'git\s+clean\s+-[a-z]*f' "Permanently deletes untracked files" || return 1
  _guard_match_bash "$cmd" 'git\s+checkout\s+--\s+\.' "Discards all working directory changes" || return 1
  _guard_match_bash "$cmd" '\bDROP\s+(TABLE|DATABASE)\b' "Destructive SQL operation" || return 1
  _guard_match_bash "$cmd" '\bTRUNCATE\b' "Truncates table data" || return 1
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

_guard_match_bash() {
  local value="$1" pattern="$2" reason="$3"
  if printf '%s' "$value" | grep -qiE -- "$pattern"; then
    _guard_block "$reason"
    return 1
  fi
  return 0
}

guard_check_prompt_secrets() {
  local prompt="$1"

  [ -z "$prompt" ] && return 0
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
