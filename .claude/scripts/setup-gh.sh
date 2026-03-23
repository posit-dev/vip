#!/usr/bin/env bash
# Auto-install GitHub CLI for Claude Code on the Web.
# Only runs in remote environments (CLAUDE_CODE_REMOTE=true).
# No Node.js, bun, or external tooling required.
#
# Environment variables:
#   GH_SETUP_VERSION  - gh CLI version to install (default: 2.88.1)
#   CLAUDE_CODE_REMOTE - must be "true" to trigger installation
#   CLAUDE_ENV_FILE    - path to env file for persisting GH_REPO and PATH

set -euo pipefail

GH_VERSION="${GH_SETUP_VERSION:-2.88.1}"
INSTALL_DIR="$HOME/.local/bin"

log() { echo "[setup-gh] $*" >&2; }

# Parse owner/repo from various git remote URL formats.
parse_gh_repo() {
    local url="$1"

    # Proxy URL: http://user@host:port/git/owner/repo
    if [[ "$url" =~ /git/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)(\.git)?$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return
    fi

    # HTTPS: https://github.com/owner/repo(.git)
    if [[ "$url" =~ github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)(\.git)?$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return
    fi

    # SSH scheme: ssh://git@github.com/owner/repo(.git)
    if [[ "$url" =~ ssh://[^/]+/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)(\.git)?$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return
    fi

    # SCP: git@github.com:owner/repo(.git)
    if [[ "$url" =~ @github\.com:([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)(\.git)?$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return
    fi
}

main() {
    # Only run in remote Claude Code environments
    if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" ]]; then
        exit 0
    fi

    # Detect architecture
    local arch
    case "$(uname -m)" in
        x86_64)        arch="amd64" ;;
        aarch64|arm64) arch="arm64" ;;
        *)
            log "Unsupported architecture: $(uname -m)"
            exit 1
            ;;
    esac

    # Persist GH_REPO and PATH additions to the session env file
    if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
        local remote_url
        remote_url="$(git remote get-url origin 2>/dev/null || true)"
        if [[ -n "$remote_url" ]]; then
            local gh_repo
            gh_repo="$(parse_gh_repo "$remote_url")"
            if [[ -n "$gh_repo" ]]; then
                echo "GH_REPO=$gh_repo" >> "$CLAUDE_ENV_FILE"
            fi
        fi
        echo "PATH=$INSTALL_DIR:\$PATH" >> "$CLAUDE_ENV_FILE"
    fi

    # Skip installation if correct version already exists
    if [[ -x "$INSTALL_DIR/gh" ]]; then
        local current_ver
        current_ver="$("$INSTALL_DIR/gh" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
        if [[ "$current_ver" == "$GH_VERSION" ]]; then
            log "gh $GH_VERSION already installed"
            exit 0
        fi
    fi

    log "Installing gh $GH_VERSION ($arch)..."

    local tarball="gh_${GH_VERSION}_linux_${arch}.tar.gz"
    local base_url="https://github.com/cli/cli/releases/download/v${GH_VERSION}"
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "$tmp_dir"' EXIT

    # Download tarball and checksums file
    curl -fsSL "$base_url/$tarball" -o "$tmp_dir/$tarball"
    curl -fsSL "$base_url/gh_${GH_VERSION}_checksums.txt" -o "$tmp_dir/checksums.txt"

    # Verify SHA256 checksum
    (cd "$tmp_dir" && grep "$tarball" checksums.txt | sha256sum --check --status)
    log "Checksum verified"

    # Extract only the gh binary
    mkdir -p "$INSTALL_DIR"
    tar -xzf "$tmp_dir/$tarball" -C "$tmp_dir" \
        --strip-components=2 \
        "gh_${GH_VERSION}_linux_${arch}/bin/gh"
    mv "$tmp_dir/gh" "$INSTALL_DIR/gh"
    chmod +x "$INSTALL_DIR/gh"

    log "gh $GH_VERSION installed to $INSTALL_DIR/gh"
}

main "$@"
