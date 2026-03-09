#!/usr/bin/env bash
set -euo pipefail

# Todo CLI installer
# Usage: curl -fsSL https://todo.app/install.sh | bash

PACKAGE_NAME="todo"
MIN_PYTHON="3.8"
REPO_URL="https://github.com/popeyef5/todo"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { printf "${CYAN}→${RESET} %s\n" "$1"; }
ok()    { printf "${GREEN}✓${RESET} %s\n" "$1"; }
warn()  { printf "${YELLOW}!${RESET} %s\n" "$1"; }
fail()  { printf "${RED}✗${RESET} %s\n" "$1"; exit 1; }

# --- Detect OS ---
detect_os() {
    case "$(uname -s)" in
        Linux*)  OS="linux" ;;
        Darwin*) OS="macos" ;;
        *)       fail "Unsupported operating system: $(uname -s)" ;;
    esac
    ARCH="$(uname -m)"
    ok "Detected ${OS} (${ARCH})"
}

# --- Find Python 3 ---
find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" 2>/dev/null; then
                PYTHON="$cmd"
                PYTHON_VERSION="$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")"
                ok "Found ${PYTHON} (${PYTHON_VERSION})"
                return 0
            fi
        fi
    done
    return 1
}

# --- Suggest how to install Python ---
suggest_python_install() {
    echo ""
    warn "Python ${MIN_PYTHON}+ is required but was not found."
    echo ""
    echo "Install it with:"
    case "$OS" in
        macos)
            echo "  brew install python3"
            echo "  # or download from https://www.python.org/downloads/"
            ;;
        linux)
            if command -v apt-get &>/dev/null; then
                echo "  sudo apt-get update && sudo apt-get install -y python3 python3-pip"
            elif command -v dnf &>/dev/null; then
                echo "  sudo dnf install -y python3 python3-pip"
            elif command -v pacman &>/dev/null; then
                echo "  sudo pacman -S python python-pip"
            elif command -v apk &>/dev/null; then
                echo "  sudo apk add python3 py3-pip"
            elif command -v zypper &>/dev/null; then
                echo "  sudo zypper install -y python3 python3-pip"
            else
                echo "  Install python3 using your system package manager"
            fi
            ;;
    esac
    echo ""
    echo "Then re-run this installer."
    exit 1
}

# --- Install via pipx (preferred) or pip ---
install_todo() {
    if command -v pipx &>/dev/null; then
        info "Installing with pipx..."
        pipx install "${PACKAGE_NAME}" 2>/dev/null \
            || pipx install "git+${REPO_URL}.git" \
            || fail "pipx install failed"
        ok "Installed with pipx"
        return
    fi

    info "pipx not found, installing with pip..."

    # Determine the right pip
    PIP=""
    for cmd in pip3 pip; do
        if command -v "$cmd" &>/dev/null; then
            if "$cmd" --version 2>/dev/null | grep -q "python 3"; then
                PIP="$cmd"
                break
            fi
        fi
    done

    # Fall back to python -m pip
    if [ -z "$PIP" ]; then
        if "$PYTHON" -m pip --version &>/dev/null; then
            PIP="$PYTHON -m pip"
        else
            fail "pip not found. Install it with: $PYTHON -m ensurepip --upgrade"
        fi
    fi

    $PIP install --user "${PACKAGE_NAME}" 2>/dev/null \
        || $PIP install --user "git+${REPO_URL}.git" \
        || fail "pip install failed"
    ok "Installed with pip"
}

# --- Verify PATH ---
check_path() {
    if command -v todo &>/dev/null; then
        ok "todo is on your PATH"
        return
    fi

    # Find where it was installed
    USER_BIN=""
    if [ -f "$HOME/.local/bin/todo" ]; then
        USER_BIN="$HOME/.local/bin"
    elif command -v pipx &>/dev/null; then
        # pipx puts binaries in its own bin dir
        PIPX_BIN="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "")"
        if [ -n "$PIPX_BIN" ] && [ -f "${PIPX_BIN}/todo" ]; then
            USER_BIN="$PIPX_BIN"
        fi
    fi

    if [ -n "$USER_BIN" ]; then
        echo ""
        warn "todo was installed but ${USER_BIN} is not in your PATH."
        echo ""
        echo "Add it by appending this to your shell config:"
        SHELL_NAME="$(basename "$SHELL")"
        case "$SHELL_NAME" in
            zsh)  echo "  echo 'export PATH=\"${USER_BIN}:\$PATH\"' >> ~/.zshrc && source ~/.zshrc" ;;
            fish) echo "  fish_add_path ${USER_BIN}" ;;
            *)    echo "  echo 'export PATH=\"${USER_BIN}:\$PATH\"' >> ~/.bashrc && source ~/.bashrc" ;;
        esac
        echo ""
    else
        warn "Could not locate the installed todo binary. You may need to add it to your PATH manually."
    fi
}

# --- Main ---
main() {
    echo ""
    printf "${BOLD}Todo CLI Installer${RESET}\n"
    echo ""

    detect_os
    find_python || suggest_python_install
    install_todo
    check_path

    echo ""
    printf "${GREEN}${BOLD}Done!${RESET} Run ${CYAN}todo${RESET} to get started.\n"
    echo ""
}

main
