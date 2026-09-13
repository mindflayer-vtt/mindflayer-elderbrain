#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
version=8.30.1
archive_sha256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
archive="gitleaks_${version}_linux_x64.tar.gz"
temporary=$(mktemp -d /tmp/elderbrain-public-audit.XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT

[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
  echo 'Public audit requires Linux x86_64 for the reviewed scanner binary' >&2
  exit 1
}
for tool in curl git python3 sha256sum tar; do
  command -v "$tool" >/dev/null || { echo "Missing public-audit tool: $tool" >&2; exit 127; }
done

curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  "https://github.com/gitleaks/gitleaks/releases/download/v${version}/${archive}" \
  --output "$temporary/$archive"
printf '%s  %s\n' "$archive_sha256" "$temporary/$archive" | sha256sum --check --status
mkdir "$temporary/tool"
tar -xzf "$temporary/$archive" -C "$temporary/tool" gitleaks
chmod 0700 "$temporary/tool/gitleaks"
[[ $("$temporary/tool/gitleaks" version) == "$version" ]]

remote=$(git -C "$root" remote get-url origin)
git clone --quiet --mirror "$remote" "$temporary/repository.git"
head=$(git -C "$root" rev-parse HEAD)
remote_head=$(git --git-dir="$temporary/repository.git" rev-parse refs/heads/main)
[[ $head == "$remote_head" ]] || {
  echo 'Local HEAD must exactly match remote main before the public audit' >&2
  exit 1
}

python3 "$root/release/public_audit_paths.py" "$temporary/repository.git"
"$temporary/tool/gitleaks" git --redact --no-banner --max-archive-depth=2 \
  --max-target-megabytes=100 --log-opts=--all "$temporary/repository.git"

mkdir "$temporary/tracked"
git -C "$root" archive --format=tar HEAD | tar -xf - -C "$temporary/tracked"
"$temporary/tool/gitleaks" dir --redact --no-banner --max-archive-depth=2 \
  --max-target-megabytes=100 "$temporary/tracked"

printf '%s\n' \
  "gitleaks version: $version" \
  "commit audited: $head" \
  'scope: every remote branch and tag, all reachable history, and current tracked files' \
  'result: pass (no secret values retained in output)'
