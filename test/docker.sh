#!/usr/bin/env bash
# Run test/tab.py against the real bash-completion of several distributions.
#
#   test/docker.sh                       # debian:bookworm-slim, debian:trixie-slim
#   test/docker.sh debian:trixie-slim    # just one
#
# The repository is mounted read-only at /src, so the harness must keep its
# fixture in the container's own temp space — which it does.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(dirname -- "$script_dir")

images=("$@")
if ((${#images[@]} == 0)); then
    images=(debian:bookworm-slim debian:trixie-slim)
fi

# Runs inside the container. uv's installer puts uv in ~/.local/bin unless
# UV_INSTALL_DIR says otherwise; we say otherwise so the path is known.
read -r -d '' in_container <<'CONTAINER_SCRIPT' || true
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq bash-completion curl ca-certificates coreutils python3 >/dev/null
export UV_INSTALL_DIR=/usr/local/bin
curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
export PATH="/usr/local/bin:$PATH"
uv --version
bash --version | head -1
grep -m1 'BASH_COMPLETION_VERSINFO=' /usr/share/bash-completion/bash_completion || true
/src/test/tab.py
CONTAINER_SCRIPT

status=0
for image in "${images[@]}"; do
    printf '\n========== %s ==========\n' "$image"
    if docker run --rm -v "$repo_root":/src:ro "$image" bash -c "$in_container"; then
        printf '%s: exit 0\n' "$image"
    else
        rc=$?
        printf '%s: exit %d\n' "$image" "$rc"
        status=1
    fi
done

exit "$status"
