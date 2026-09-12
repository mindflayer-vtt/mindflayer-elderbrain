#!/bin/bash
# Runs only inside the freshly installed disposable test VM.
set -euo pipefail
runtime=/opt/mindflayer-elderbrain
compose=(docker compose --env-file "$runtime/appliance.env" -f "$runtime/compose.yaml")
for attempt in $(seq 1 120); do
  [[ $(systemctl is-active elderbrain-stack) == active ]] && break
  if [[ $(systemctl is-failed elderbrain-stack) == failed ]]; then
    journalctl -u elderbrain-stack --no-pager -n 100
    exit 1
  fi
  sleep 5
done
for service in docker elderbrain-stack elderbrain-management elderbrain-graphics; do
  for attempt in $(seq 1 60); do
    status=$(systemctl is-active "$service" || true)
    [[ $status == active ]] && break
    [[ $status == failed ]] && break
    sleep 1
  done
  if [[ $status != active ]]; then
    echo "Guest service $service did not become active (state=$status)" >&2
    journalctl -u "$service" --no-pager -n 30
    exit 1
  fi
done
for attempt in $(seq 1 30); do
  kiosk_pid=$(systemctl show elderbrain-graphics --property=MainPID --value)
  kiosk_executable=$(readlink "/proc/$kiosk_pid/exe" || true)
  if [[ $kiosk_executable == /usr/bin/sway ]] && pgrep -u elderbrain-kiosk -x chrome >/dev/null; then break; fi
  sleep 1
done
[[ $kiosk_executable == /usr/bin/sway ]] || { echo 'Kiosk has not executed its compositor' >&2; exit 1; }
pgrep -u elderbrain-kiosk -x chrome >/dev/null || { echo 'Kiosk browser is not running' >&2; exit 1; }
"${compose[@]}" ps
"${compose[@]}" images
configured=$(sed -n 's/^MINDFLAYER_SERVER_IMAGE=//p' "$runtime/appliance.env")
container=$("${compose[@]}" ps -q mindflayer-server)
[[ $(docker inspect "$container" --format '{{.Image}}') == $(docker image inspect "$configured" --format '{{.Id}}') ]]
docker image inspect "$configured" --format 'configured={{index .RepoDigests 0}} id={{.Id}}'
"${compose[@]}" exec -T mindflayer-server node scripts/installation-capabilities.js < /dev/null | python3 -c '
import json, sys
capabilities = json.load(sys.stdin)
assert 3 in capabilities["deviceProtocolVersions"]
assert capabilities["configurationProof"] == "sha256-canonical-envelope-v2"
'
"$runtime/serial-venv/bin/python" "$runtime/esptool-runner.py" version < /dev/null
python3 -c '
from pathlib import Path
import stat
root = Path("/var/lib/mindflayer-elderbrain/keypad-installations")
info = root.stat()
assert root.is_dir() and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700
runtime = Path("/opt/mindflayer-elderbrain")
for name in ("installation_job.py", "installation_backend.py", "installation_server.py", "serial_install.py", "serial_bundle.py", "serial_release.py", "serial_provision.py"):
    assert (runtime / name).is_file(), name
'
[[ $("${compose[@]}" ps --services --status running | wc -l) -eq 3 ]]
curl --noproxy '*' -fsS -H 'Host: mindflayer.elderbrain.local' http://127.0.0.1/ >/dev/null
# Device TLS uses a separately pinned key, not the administration CA.
[[ $(curl --noproxy '*' -ksS -o /dev/null -w '%{http_code}' https://127.0.0.1:10443/) == 404 ]]
! dpkg -s ubuntu-desktop >/dev/null 2>&1
# Prove that the actual Setup container has the dedicated capability and can use
# the scoped host bridge; UID 1000 alone is not the authority.
[[ $(getent group elderbrain-management | cut -d: -f3) == 31338 ]]
[[ $(stat -c '%U:%G:%a' /run/elderbrain/management.sock) == root:elderbrain-management:660 ]]
[[ $("${compose[@]}" exec -T elderbrain-setup id -g < /dev/null) == 31338 ]]
"${compose[@]}" exec -T elderbrain-setup node --input-type=module -e '
import net from "node:net";
const socket = net.createConnection("/run/elderbrain/management.sock");
let output = "";
socket.setTimeout(5000, () => socket.destroy(new Error("bridge timeout")));
socket.on("connect", () => socket.end("keypad-registrations\n"));
socket.on("data", chunk => { output += chunk; });
socket.on("end", () => {
  const result = JSON.parse(output);
  if (!result.ok || !Array.isArray(JSON.parse(result.output))) process.exitCode = 1;
});
socket.on("error", () => { process.exitCode = 1; });
' < /dev/null
echo 'Verified installed v3 capabilities, serial tooling, private journal storage and setup host bridge'
