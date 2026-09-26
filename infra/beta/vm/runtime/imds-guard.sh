#!/bin/sh
set -eu
# Run on the Linux host before any Compose start, including after a host reboot.
# Only the two fixed application IPs on our exact egress bridge may reach IMDS.
[ "$(id -u)" = 0 ] || { echo 'IMDS guard requires host root' >&2; exit 1; }
command -v iptables >/dev/null
iptables -w -S DOCKER-USER >/dev/null
# A failed replacement leaves all container access to IMDS denied.
iptables -w -I DOCKER-USER 1 -d 169.254.169.254/32 -m comment --comment cosmabot-imds-install-deny -j REJECT
if ! iptables -w -S COSMABOT-IMDS >/dev/null 2>&1; then
    iptables -w -N COSMABOT-IMDS
fi
iptables -w -F COSMABOT-IMDS
for source in 172.30.241.10/32 172.30.241.11/32; do
    iptables -w -A COSMABOT-IMDS -i br-cm-egress -s "$source" -j RETURN
done
iptables -w -A COSMABOT-IMDS -j REJECT
while iptables -w -C DOCKER-USER -d 169.254.169.254/32 -j COSMABOT-IMDS 2>/dev/null; do
    iptables -w -D DOCKER-USER -d 169.254.169.254/32 -j COSMABOT-IMDS
done
iptables -w -I DOCKER-USER 1 -d 169.254.169.254/32 -j COSMABOT-IMDS
iptables -w -C DOCKER-USER -d 169.254.169.254/32 -j COSMABOT-IMDS
while iptables -w -C DOCKER-USER -d 169.254.169.254/32 -m comment --comment cosmabot-imds-install-deny -j REJECT 2>/dev/null; do
    iptables -w -D DOCKER-USER -d 169.254.169.254/32 -m comment --comment cosmabot-imds-install-deny -j REJECT
done
