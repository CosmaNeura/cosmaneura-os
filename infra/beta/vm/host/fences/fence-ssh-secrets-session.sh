cosmabot_ssh_secrets_session() {
  cosmabot_ssh_nsg_open || {
    echo "STOP: session open failed - forcing close-and-verify" >&2
    cosmabot_ssh_nsg_close_and_verify || true
    return 1
  }
  if ! cosmabot_ssh_secrets_install; then
    echo "STOP: session install failed - forcing close-and-verify" >&2
    cosmabot_ssh_nsg_close_and_verify || true
    return 1
  fi
  cosmabot_ssh_nsg_close_and_verify || {
    echo "STOP: session close-and-verify failed - fix before any Terraform plan or apply" >&2
    return 1
  }
  echo "PASS: secrets SSH session complete (open, install, close-and-verify)"
  return 0
}
