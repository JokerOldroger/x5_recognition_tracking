#!/usr/bin/env bash
set -e
if [[ "$EUID" -ne 0 ]]; then
    echo "Run: sudo bash install_service.sh" >&2
    exit 1
fi
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-sunrise}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
[[ -n "$RUN_HOME" ]] || { echo "Unknown user: $RUN_USER"; exit 1; }
[[ "$APP_DIR" != *'"'* && "$APP_DIR" != *'%'* && "$APP_DIR" != *$'\n'* ]] || exit 1
if systemctl is-active --quiet dingdong; then
    echo "Stop the existing service before reinstalling: sudo systemctl stop dingdong"
    exit 1
fi
cat > /etc/systemd/system/dingdong.service <<EOF
[Unit]
Description=DINGDONG gesture recognition and H60 motion
After=local-fs.target network-online.target time-sync.target

[Service]
Type=simple
User=$RUN_USER
SupplementaryGroups=dialout video
Environment="HOME=$RUN_HOME"
Environment="PYTHONUNBUFFERED=1"
# run.sh resolves its own directory and changes into runtime itself.
ExecStart=/bin/bash "$APP_DIR/run.sh"
# Deliberately never restart automatically: a restart would reacquire control.
Restart=no
KillMode=control-group
KillSignal=SIGINT
TimeoutStopSec=10
UMask=0022

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable dingdong.service
echo 'Installed. Start with: sudo systemctl start dingdong'
echo 'Logs: journalctl -u dingdong -f'
