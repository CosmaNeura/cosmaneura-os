cosmabot_ssh_session_save_traps() {
  if test -n "${ZSH_VERSION:-}"; then
    if typeset -f TRAPINT >/dev/null 2>&1 \
      || typeset -f TRAPTERM >/dev/null 2>&1 \
      || typeset -f TRAPEXIT >/dev/null 2>&1; then
      echo "STOP: zsh TRAPxxx function traps present - run this fence in a fresh terminal" >&2
      return 1
    fi
    _ssh_sess_trap_tmp="${TMPDIR:-/tmp}/.cosmabot-ssh-sess-traps.$$"
    trap >"$_ssh_sess_trap_tmp" || {
      rm -f "$_ssh_sess_trap_tmp"
      echo "STOP: zsh trap save failed - run this fence in a fresh terminal" >&2
      return 1
    }
    _ssh_sess_prev_exit=
    _ssh_sess_prev_int=
    _ssh_sess_prev_term=
    while IFS= read -r _trap_line || test -n "${_trap_line:-}"; do
      case "$_trap_line" in
        *" EXIT") _ssh_sess_prev_exit=$_trap_line ;;
        *" INT"|*" SIGINT") _ssh_sess_prev_int=$_trap_line ;;
        *" TERM"|*" SIGTERM") _ssh_sess_prev_term=$_trap_line ;;
      esac
    done <"$_ssh_sess_trap_tmp"
    rm -f "$_ssh_sess_trap_tmp"
  else
    _ssh_sess_prev_exit=$(trap -p EXIT)
    _ssh_sess_prev_int=$(trap -p INT)
    _ssh_sess_prev_term=$(trap -p TERM)
  fi
  return 0
}
cosmabot_ssh_session_restore_traps() {
  if test -n "${_ssh_sess_prev_exit:-}"; then
    printf '%s\n' 'eval "${_ssh_sess_prev_exit}"'
  else
    printf '%s\n' 'trap - EXIT'
  fi
  if test -n "${_ssh_sess_prev_int:-}"; then
    printf '%s\n' 'eval "${_ssh_sess_prev_int}"'
  else
    printf '%s\n' 'trap - INT'
  fi
  if test -n "${_ssh_sess_prev_term:-}"; then
    printf '%s\n' 'eval "${_ssh_sess_prev_term}"'
  else
    printf '%s\n' 'trap - TERM'
  fi
  printf '%s\n' 'unset _ssh_sess_prev_exit _ssh_sess_prev_int _ssh_sess_prev_term'
}
cosmabot_ssh_secrets_session() {
  command -v cosmabot_ssh_nsg_open >/dev/null || {
    echo "STOP: session needs cosmabot_ssh_nsg_open sourced" >&2
    return 1
  }
  command -v cosmabot_ssh_secrets_install >/dev/null || {
    echo "STOP: session needs cosmabot_ssh_secrets_install sourced" >&2
    return 1
  }
  command -v cosmabot_ssh_nsg_close_and_verify >/dev/null || {
    echo "STOP: session needs cosmabot_ssh_nsg_close_and_verify sourced" >&2
    return 1
  }
  _cosmabot_ssh_session_done=0
  _cosmabot_ssh_session_cleanup() {
    if test "${_cosmabot_ssh_session_done}" = "1"; then
      return 0
    fi
    _cosmabot_ssh_session_done=1
    if test -n "${LOCAL_STAGING:-}" && test -e "${LOCAL_STAGING}"; then
      rm -rf "${LOCAL_STAGING:?}"
    fi
    if test -n "${SSH_KNOWN_HOSTS_FILE:-}" && test -e "${SSH_KNOWN_HOSTS_FILE}"; then
      rm -f "${SSH_KNOWN_HOSTS_FILE}"
    fi
    cosmabot_ssh_nsg_close_and_verify
  }
  cosmabot_ssh_session_save_traps || return 1
  trap '_cosmabot_ssh_session_cleanup' EXIT INT TERM
  cosmabot_ssh_nsg_open || {
    echo "STOP: session open failed - close-and-verify via guarded cleanup" >&2
    _cosmabot_ssh_session_cleanup
    eval "$(cosmabot_ssh_session_restore_traps)"
    return 1
  }
  cosmabot_ssh_secrets_install || {
    echo "STOP: session install failed - close-and-verify via guarded cleanup" >&2
    _cosmabot_ssh_session_cleanup
    eval "$(cosmabot_ssh_session_restore_traps)"
    return 1
  }
  _cosmabot_ssh_session_cleanup || {
    echo "STOP: session close-and-verify failed - fix before any Terraform plan or apply" >&2
    eval "$(cosmabot_ssh_session_restore_traps)"
    return 1
  }
  eval "$(cosmabot_ssh_session_restore_traps)"
  echo "PASS: secrets SSH session complete (open, install, close-and-verify)"
  return 0
}
