#!/usr/bin/env bash
# Run the test suites against the real bash-completion of several
# distributions, plus a source build of a version no distribution ships yet.
#
#   test/docker.sh                            # the default matrix below
#   test/docker.sh debian:trixie-slim         # one distro's own bash-completion
#   test/docker.sh debian:trixie-slim=2.18.0  # that distro, bash-completion built from source
#
# An entry is IMAGE or IMAGE=BC_VERSION. The separator is `=` because it
# cannot appear in a Docker image reference, so a digest-pinned image such as
# debian:trixie-slim@sha256:... still names the image and nothing else. With a
# version, the named
# bash-completion release is unpacked under /opt/bc and used instead of the
# packaged one, which is how a version no distro has packaged yet gets tested.
#
# The repository is mounted read-only at /src, so the harness must keep its
# fixture in the container's own temp space — which it does.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(dirname -- "$script_dir")

entries=("$@")
if ((${#entries[@]} == 0)); then
    entries=(
        debian:bookworm-slim            # bash-completion 2.11
        debian:trixie-slim              # bash-completion 2.16.0
        debian:trixie-slim=2.18.0       # current upstream, no distro ships it yet
    )
fi

# Runs inside the container. uv's installer puts uv in ~/.local/bin unless
# UV_INSTALL_DIR says otherwise; we say otherwise so the path is known.
read -r -d '' in_container <<'CONTAINER_SCRIPT' || true
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq bash-completion curl ca-certificates coreutils >/dev/null
export UV_INSTALL_DIR=/usr/local/bin
curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
export PATH="/usr/local/bin:$PATH"

bc=/usr/share/bash-completion/bash_completion
if [ -n "${BC_VERSION:-}" ]; then
    mkdir -p /opt/bc
    curl -fsSL "https://github.com/scop/bash-completion/archive/refs/tags/${BC_VERSION}.tar.gz" \
        | tar -xz -C /opt/bc --strip-components=1
    bc=/opt/bc/bash_completion
fi

uv --version
bash --version | head -1
bash -ic "source $bc; printf 'bash-completion: %s\n' \"\${BASH_COMPLETION_VERSINFO[*]}\"" 2>/dev/null

/src/test/tab.py --bash-completion "$bc"

# install.sh only touches $HOME, and the suite makes its own throwaway HOMEs.
/src/test/installer.sh
CONTAINER_SCRIPT

status=0
for entry in "${entries[@]}"; do
    image=${entry%%=*}
    bc_version=""
    [[ $entry == *=* ]] && bc_version=${entry#*=}

    if [[ -n $bc_version ]]; then
        printf '\n========== %s, bash-completion %s from source ==========\n' "$image" "$bc_version"
    else
        printf '\n========== %s, packaged bash-completion ==========\n' "$image"
    fi

    if docker run --rm -e BC_VERSION="$bc_version" -v "$repo_root":/src:ro "$image" bash -c "$in_container"; then
        printf '%s: exit 0\n' "$entry"
    else
        rc=$?
        printf '%s: exit %d\n' "$entry" "$rc"
        status=1
    fi
done

exit "$status"
