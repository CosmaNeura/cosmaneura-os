# shellcheck shell=bash
# Bash 3-compatible startup isolation for human-side D3 deployment wrappers.
# Call this before parsing arguments, sourcing deployment guards, or reading
# private artifacts. Production invocation must use `/bin/bash -p SCRIPT ...`
# so BASH_ENV and imported shell options/functions are suppressed pre-body.

cosmas_isolate_local_wrapper_environment() {
  set +x
  case "$-" in
    *p*) ;;
    *)
      printf '%s\n' \
        "D3 deployment wrapper refused: invoke with /bin/bash -p, not an ambient shell" >&2
      exit 1
      ;;
  esac

  _cosmas_protected_context=false
  if [ "${COSMAS_PROTECTED_WRAPPER_CONTEXT:-}" = "1" ] && \
    [ "$(/usr/bin/id -u)" = "0" ] && \
    [ -f /var/lib/cosmas-deploy-runner/toolchain.json ] && \
    [ ! -L /var/lib/cosmas-deploy-runner/toolchain.json ] && \
    [ "$(/usr/bin/stat -c '%u:%a' /var/lib/cosmas-deploy-runner/toolchain.json 2>/dev/null)" = "0:600" ] && \
    [[ "${AZURE_CONFIG_DIR:-}" =~ ^/run/cosmas-azure-session\.[A-Za-z0-9]+$ ]] && \
    [ -d "$AZURE_CONFIG_DIR" ] && [ ! -L "$AZURE_CONFIG_DIR" ] && \
    [ "$(/usr/bin/stat -c '%u:%a' "$AZURE_CONFIG_DIR" 2>/dev/null)" = "0:700" ] && \
    [ "${ARM_USE_MSI:-}" = "true" ] && [ "${ARM_USE_AZUREAD:-}" = "true" ] && \
    [[ "${ARM_CLIENT_ID:-}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] && \
    [[ "${ARM_SUBSCRIPTION_ID:-}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] && \
    [[ "${ARM_TENANT_ID:-}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] && \
    [ "${COSMAS_TERRAFORM_BIN:-}" = "/usr/local/bin/tofu" ] && \
    [ "${TF_IN_AUTOMATION:-}" = "1" ]; then
    _cosmas_protected_context=true
  fi

  if [ "$_cosmas_protected_context" = "true" ]; then
    _cosmas_clean_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    _cosmas_home=/root
  else
    _cosmas_clean_path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    _cosmas_home=""
  fi
  _cosmas_python=""
  for _cosmas_candidate in \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    /usr/bin/python3; do
    if [ -x "$_cosmas_candidate" ] && \
      "$_cosmas_candidate" -I -E -s -c \
        'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        >/dev/null 2>&1; then
      _cosmas_python="$_cosmas_candidate"
      break
    fi
  done
  [ -n "$_cosmas_python" ] || {
    printf '%s\n' "D3 deployment wrapper refused: fixed Python 3.10+ is unavailable" >&2
    exit 1
  }
  if [ -z "$_cosmas_home" ]; then
    _cosmas_home="$("$_cosmas_python" -I -E -s -c \
      'import os,pwd; print(pwd.getpwuid(os.getuid()).pw_dir)' 2>/dev/null)"
  fi
  case "$_cosmas_home" in
    /*) ;;
    *)
      printf '%s\n' "D3 deployment wrapper refused: user home lookup failed" >&2
      exit 1
      ;;
  esac

  _cosmas_bash=""
  for _cosmas_candidate in \
    /opt/homebrew/bin/bash \
    /usr/local/bin/bash \
    /bin/bash; do
    # Expansion must occur in the candidate shell.
    # shellcheck disable=SC2016
    if [ -x "$_cosmas_candidate" ] && \
      [ "$("$_cosmas_candidate" --noprofile --norc -p -c \
        'printf "%s" "${BASH_VERSINFO[0]}"' 2>/dev/null)" -ge 5 ] 2>/dev/null; then
      _cosmas_bash="$_cosmas_candidate"
      break
    fi
  done
  [ -n "$_cosmas_bash" ] || {
    printf '%s\n' "D3 deployment wrapper refused: fixed Bash 5+ is unavailable" >&2
    exit 1
  }

  _cosmas_environment_clean=true
  while IFS='=' read -r _cosmas_name _cosmas_value; do
    case "$_cosmas_name" in
      COSMAS_GUARDED_ENVIRONMENT|HOME|LANG|LC_ALL|PATH|PWD|SHLVL|_) ;;
      AZURE_CONFIG_DIR|ARM_USE_MSI|ARM_USE_AZUREAD|ARM_CLIENT_ID|ARM_SUBSCRIPTION_ID|ARM_TENANT_ID|COSMAS_TERRAFORM_BIN|TF_IN_AUTOMATION|COSMAS_PROTECTED_WRAPPER_CONTEXT)
        [ "$_cosmas_protected_context" = "true" ] || _cosmas_environment_clean=false
        ;;
      *) _cosmas_environment_clean=false ;;
    esac
  done < <(/usr/bin/env)

  if [ "${COSMAS_GUARDED_ENVIRONMENT:-}" != "1" ] || \
    [ "$_cosmas_environment_clean" != "true" ] || \
    [ "${BASH_VERSINFO[0]:-0}" -lt 5 ] || \
    [ "${PATH:-}" != "$_cosmas_clean_path" ] || \
    [ "${HOME:-}" != "$_cosmas_home" ] || \
    [ "${LANG:-}" != "C" ] || [ "${LC_ALL:-}" != "C" ]; then
    if [ "$_cosmas_protected_context" = "true" ]; then
      exec /usr/bin/env -i \
        PATH="$_cosmas_clean_path" HOME=/root LANG=C LC_ALL=C \
        COSMAS_GUARDED_ENVIRONMENT=1 COSMAS_PROTECTED_WRAPPER_CONTEXT=1 \
        AZURE_CONFIG_DIR="$AZURE_CONFIG_DIR" \
        ARM_USE_MSI=true ARM_USE_AZUREAD=true \
        ARM_CLIENT_ID="$ARM_CLIENT_ID" ARM_SUBSCRIPTION_ID="$ARM_SUBSCRIPTION_ID" \
        ARM_TENANT_ID="$ARM_TENANT_ID" COSMAS_TERRAFORM_BIN=/usr/local/bin/tofu \
        TF_IN_AUTOMATION=1 \
        "$_cosmas_bash" --noprofile --norc -p "$0" "$@"
    fi
    exec /usr/bin/env -i \
      PATH="$_cosmas_clean_path" HOME="$_cosmas_home" LANG=C LC_ALL=C \
      COSMAS_GUARDED_ENVIRONMENT=1 \
      "$_cosmas_bash" --noprofile --norc -p "$0" "$@"
  fi

  unset COSMAS_GUARDED_ENVIRONMENT COSMAS_PROTECTED_WRAPPER_CONTEXT \
    BASH_ENV ENV CDPATH PYTHONHOME PYTHONPATH \
    PYTHONSTARTUP BASH_XTRACEFD PS4
  unset _cosmas_clean_path _cosmas_python _cosmas_home _cosmas_bash \
    _cosmas_candidate _cosmas_environment_clean _cosmas_protected_context \
    _cosmas_name _cosmas_value
}
