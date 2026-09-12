#!/bin/bash
# Run inside `unshare --net` on the disposable appliance; keep test evidence.
set -euo pipefail
[[ $(id -u) == 0 ]]
[[ $(lsblk -dn -o SERIAL /dev/vda) == elderbrain-vm-test ]]
[[ $(readlink /proc/self/ns/net) != "$(readlink /proc/1/ns/net)" ]] || { echo 'Use an isolated network namespace.' >&2; exit 2; }
dep_bundle=${1:?Pass the freshly built private dependency bundle directory}
dep_inputs=${2:?Pass the reviewed requirements directory}
[[ $dep_bundle == /* && -d $dep_bundle && $dep_inputs == /* && -d $dep_inputs ]]
dep_test=$(mktemp -d /root/elderbrain-offline-deps-XXXXXXXX)
printf 'Offline test directory: %s\n' "$dep_test"
for component in serial borgmatic; do
  python3 -m venv "$dep_test/$component"
  "$dep_test/$component/bin/pip" install --no-index --no-deps --find-links "$dep_bundle/wheels" -r "$dep_inputs/$component-requirements.txt" --quiet
  "$dep_test/$component/bin/pip" check
done
"$dep_test/serial/bin/python" -c 'import esptool; assert esptool.__version__ == "4.9.0"; print("Offline esptool import passed")'
"$dep_test/borgmatic/bin/borgmatic" --version
mkdir "$dep_test/browser"
npm install --offline --ignore-scripts --omit=dev --no-audit --no-fund --prefix "$dep_test/browser" "$dep_bundle/node/playwright-core-1.63.0.tgz"
node -e 'const p = require(process.argv[1]); if (!p.chromium) process.exit(1); console.log("Offline browser-helper import passed")' "$dep_test/browser/node_modules/playwright-core"
printf 'PASS: both Python environments and browser helper installed with networking disabled\n'
