#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# The tag documents the reviewed tool version; the digest authenticates the
# exact linux/amd64 image rather than trusting a mutable registry tag.
image='rhysd/actionlint:1.7.10@sha256:ef8299f97635c4c30e2298f48f30763ab782a4ad2c95b744649439a039421e36'

relative=("$@")
if (( ${#relative[@]} == 0 )); then
  mapfile -d '' workflows < <(find "$root/.github/workflows" -maxdepth 1 -type f -name '*.yml' -print0 | sort -z)
  (( ${#workflows[@]} > 0 )) || { echo 'No GitHub Actions workflows found' >&2; exit 1; }
  for workflow in "${workflows[@]}"; do relative+=("${workflow#"$root/"}"); done
fi

# actionlint 1.7.10 predates GitHub's hosted Ubuntu 26.04 label. Ignore only
# that exact catalogue warning; expression/context/schema errors remain fatal.
docker run --rm --platform linux/amd64 -v "$root:/repo:ro" -w /repo "$image" \
  -ignore 'label "ubuntu-26.04" is unknown' "${relative[@]}"
