cosmabot_ssh_secrets_session() {
  test "$(type -t cosmabot_ssh_nsg_open)" = "function" || {
    echo "STOP: session needs cosmabot_ssh_nsg_open sourced" >&2
    return 1
  }
  test "$(type -t cosmabot_ssh_secrets_install)" = "function" || {
    echo "STOP: session needs cosmabot_ssh_secrets_install sourced" >&2
    return 1
  }
  test "$(type -t cosmabot_ssh_nsg_close_and_verify)" = "function" || {
    echo "STOP: session needs cosmabot_ssh_nsg_close_and_verify sourced" >&2
    return 1
  }
  _cosmabot_ssh_session_cleanup() {
    if test -n "${LOCAL_STAGING:-}" && test -e "${LOCAL_STAGING}"; then
      rm -rf "${LOCAL_STAGING:?}" 2>/dev/null || true
    fi
    if test -n "${SSH_KNOWN_HOSTS_FILE:-}" && test -e "${SSH_KNOWN_HOSTS_FILE}"; then
      rm -f "${SSH_KNOWN_HOSTS_FILE}" 2>/dev/null || true
    fi
    cosmabot_ssh_nsg_close_and_verify || true
  }
  trap '_cosmabot_ssh_session_cleanup' EXIT INT TERM ERR
  cosmabot_ssh_nsg_open || {
    echo "STOP: session open failed - close-and-verify via trap" >&2
    return 1
  }
  cosmabot_ssh_secrets_install || {
    echo "STOP: session install failed - close-and-verify via trap" >&2
    return 1
  }
  trap - ERR
  cosmabot_ssh_nsg_close_and_verify || {
    echo "STOP: session close-and-verify failed - fix before any Terraform plan or apply" >&2
    trap - EXIT INT TERM
    return 1
  }
  trap - EXIT INT TERM
  if test -n "${LOCAL_STAGING:-}" && test -e "${LOCAL_STAGING}"; then
    rm -rf "${LOCAL_STAGING:?}"
  fi
  if test -n "${SSH_KNOWN_HOSTS_FILE:-}" && test -e "${SSH_KNOWN_HOSTS_FILE}"; then
    rm -f "${SSH_KNOWN_HOSTS_FILE}"
  fi
  echo "PASS: secrets SSH session complete (open, install, close-and-verify)"
  return 0
}
