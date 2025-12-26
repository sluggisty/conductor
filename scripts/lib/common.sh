#!/bin/bash
# common.sh - Common functions and configuration for conductor scripts
# ===================================================================

# Script directory detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDUCTOR_DIR="$(dirname "$SCRIPT_DIR")"

# Default configuration
VM_COUNT_PER_VERSION="${VM_COUNT_PER_VERSION:-5}"
VM_PREFIX="${VM_PREFIX:-conductor-test}"
MEMORY_MB="${MEMORY_MB:-2048}"
VCPUS="${VCPUS:-2}"
DISK_SIZE_GB="${DISK_SIZE_GB:-15}"
IMAGE_DIR="${IMAGE_DIR:-/var/lib/libvirt/images}"
CLOUDINIT_DIR="${CLOUDINIT_DIR:-/tmp/conductor-test-cloudinit}"
SSH_KEY_PATH="${SSH_KEY_PATH:-${HOME}/.ssh/conductor-test-key}"

# VM user credentials
VM_USER="${VM_USER:-conductor}"
VM_PASSWORD="${VM_PASSWORD:-conductortest123}"

# Snail core configuration (API endpoint and key for uploads)
# Note: snail-core is now installed via pip install snail-core
SNAIL_API_ENDPOINT="${SNAIL_API_ENDPOINT:-http://192.168.124.1:8080/api/v1/ingest}"
# Don't set a default API key - let snail-core fetch it automatically
# Set to empty string to avoid "unbound variable" errors, but snail-core will fetch it
SNAIL_API_KEY="${SNAIL_API_KEY:-}"

# Distribution and versions to create
# Format: "distro:version" or just "version" (defaults to fedora)
# Examples: "fedora:42,41" or "debian:12,11" or "42,41" (assumes fedora)
VM_SPECS="${VM_SPECS:-fedora:42}"

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
}

# Check requirements
check_requirements() {
    local missing=()
    
    for cmd in virsh virt-install qemu-img genisoimage; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required tools: ${missing[*]}"
        log_info "Install with: sudo dnf install libvirt virt-install qemu-img genisoimage"
        exit 1
    fi
    
    # Check if libvirtd is running
    if ! systemctl is-active --quiet libvirtd; then
        log_error "libvirtd is not running"
        log_info "Start with: sudo systemctl start libvirtd"
        exit 1
    fi
}

# Generate SSH key if needed
setup_ssh_key() {
    if [[ ! -f "$SSH_KEY_PATH" ]]; then
        log_info "Generating SSH key pair..."
        ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -N "" -C "conductor-test-vms"
        log_success "SSH key generated: ${SSH_KEY_PATH}"
    else
        log_info "Using existing SSH key: ${SSH_KEY_PATH}"
    fi
}

# Parse VM spec (format: "distro:version" or just "version")
parse_vm_spec() {
    local spec="$1"
    local default_distro="${2:-fedora}"
    
    if [[ "$spec" == *:* ]]; then
        echo "$spec"
    else
        echo "${default_distro}:${spec}"
    fi
}

# Create directory with proper permissions, using sudo if needed
ensure_directory() {
    local dir_path="$1"
    local owner="${2:-$USER}"
    
    # Check if directory is in a system path that requires root
    local needs_sudo=false
    if [[ "$dir_path" == /var/* ]] || \
       [[ "$dir_path" == /usr/* ]] || \
       [[ "$dir_path" == /etc/* ]] || \
       [[ "$dir_path" == /opt/* ]]; then
        needs_sudo=true
    fi
    
    # Check if parent directory exists and is writable
    local parent_dir=$(dirname "$dir_path")
    if [[ ! -w "$parent_dir" ]] && [[ "$parent_dir" != "/" ]]; then
        needs_sudo=true
    fi
    
    if [[ "$needs_sudo" == true ]]; then
        # Create directory with sudo and set ownership
        if [[ ! -d "$dir_path" ]]; then
            sudo mkdir -p "$dir_path"
            sudo chown "$owner:$owner" "$dir_path"
            sudo chmod 755 "$dir_path"
        else
            # Directory exists, ensure ownership is correct
            local current_owner=$(stat -c '%U' "$dir_path" 2>/dev/null || echo "")
            if [[ "$current_owner" != "$owner" ]]; then
                sudo chown "$owner:$owner" "$dir_path"
            fi
        fi
    else
        # Create directory normally
        mkdir -p "$dir_path"
    fi
}

# Check if a path needs sudo for file operations
needs_sudo_for_path() {
    local path="$1"
    
    # Check if path is in a system directory
    if [[ "$path" == /var/* ]] || \
       [[ "$path" == /usr/* ]] || \
       [[ "$path" == /etc/* ]] || \
       [[ "$path" == /opt/* ]]; then
        return 0  # true - needs sudo
    fi
    
    # Check if parent directory is writable
    local parent_dir=$(dirname "$path")
    if [[ ! -w "$parent_dir" ]] && [[ "$parent_dir" != "/" ]]; then
        return 0  # true - needs sudo
    fi
    
    return 1  # false - doesn't need sudo
}



