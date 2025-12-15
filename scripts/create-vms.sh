#!/bin/bash
# create-vms.sh - Create multiple VMs for conductor testing
# ==========================================================================
# This script orchestrates VM creation using modular components from lib/

set -euo pipefail

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDUCTOR_DIR="$(dirname "$SCRIPT_DIR")"

# Source all required modules
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/images.sh"
source "${SCRIPT_DIR}/lib/vm.sh"

# Main function
main() {
    echo ""
    echo "=========================================="
    echo "    Conductor VM Test Environment"
    echo "=========================================="
    echo ""
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --specs|-s)
                VM_SPECS="$2"
                shift 2
                ;;
            --count|-n)
                VM_COUNT_PER_VERSION="$2"
                shift 2
                ;;
            --prefix|-p)
                VM_PREFIX="$2"
                shift 2
                ;;
            --memory|-m)
                MEMORY_MB="$2"
                shift 2
                ;;
            --cpus|-c)
                VCPUS="$2"
                shift 2
                ;;
            --help|-h)
                echo "Usage: $0 [options]"
                echo ""
                echo "Options:"
                echo "  --specs, -s LIST      Comma-separated VM specs (default: fedora:42)"
                echo "                       Format: distro:version or just version (defaults to fedora)"
                echo "                       Examples: fedora:42,41 or debian:12,11 or 42,41"
                echo "  --count, -n NUM      Number of VMs per version (default: 5)"
                echo "  --prefix, -p NAME    VM name prefix (default: conductor-test)"
                echo "  --memory, -m MB      Memory per VM in MB (default: 2048)"
                echo "  --cpus, -c NUM       vCPUs per VM (default: 2)"
                echo ""
                echo "Examples:"
                echo "  $0 --specs fedora:42,41,40"
                echo "  $0 --specs debian:12,11"
                echo "  $0 --specs fedora:42,debian:12"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    log_info "Configuration:"
    log_info "  VM Specs: ${VM_SPECS}"
    log_info "  VMs per Version: ${VM_COUNT_PER_VERSION}"
    log_info "  VM Prefix: ${VM_PREFIX}"
    log_info "  Memory: ${MEMORY_MB} MB"
    log_info "  vCPUs: ${VCPUS}"
    echo ""
    
    check_requirements
    setup_ssh_key
    
    # Verify base images exist for all specs
    log_info "Checking base images..."
    IFS=',' read -ra SPECS <<< "$VM_SPECS"
    local missing_specs=()
    for spec in "${SPECS[@]}"; do
        local parsed_spec
        parsed_spec=$(parse_vm_spec "$spec")
        IFS=':' read -r distro version <<< "$parsed_spec"
        if ! check_base_image "$distro" "$version"; then
            missing_specs+=("${distro}:${version}")
        fi
    done
    
    if [[ ${#missing_specs[@]} -gt 0 ]]; then
        log_error "Missing base images for: ${missing_specs[*]}"
        log_info "Download them with:"
        for spec in "${missing_specs[@]}"; do
            IFS=':' read -r distro version <<< "$spec"
            log_info "  ./scripts/setup-base-image.sh --distro ${distro} --version ${version}"
        done
        exit 1
    fi
    
    # Create cloud-init directory
    mkdir -p "$CLOUDINIT_DIR"
    
    # Create VMs for each spec
    local vm_counter=1
    IFS=',' read -ra SPECS <<< "$VM_SPECS"
    for spec in "${SPECS[@]}"; do
        local parsed_spec
        parsed_spec=$(parse_vm_spec "$spec")
        IFS=':' read -r distro version <<< "$parsed_spec"
        log_info ""
        log_info "Creating VMs for ${distro^} ${version}..."
        for i in $(seq 1 "$VM_COUNT_PER_VERSION"); do
            create_vm \
                "${VM_PREFIX}-${distro}-${version}-${i}" \
                "$vm_counter" \
                "$distro" \
                "$version"
            vm_counter=$((vm_counter + 1))
        done
    done
    
    echo ""
    wait_for_vms
    show_vm_info
    
    # Save VM list for later use
    local vm_list_file="${CONDUCTOR_DIR}/vm-list.txt"
    > "$vm_list_file"
    IFS=',' read -ra SPECS <<< "$VM_SPECS"
    for spec in "${SPECS[@]}"; do
        local parsed_spec
        parsed_spec=$(parse_vm_spec "$spec")
        IFS=':' read -r distro version <<< "$parsed_spec"
        for i in $(seq 1 "$VM_COUNT_PER_VERSION"); do
            echo "${VM_PREFIX}-${distro}-${version}-${i}"
        done
    done >> "$vm_list_file"
    
    log_success "VM creation complete!"
    log_info "VM list saved to: ${vm_list_file}"
    log_info ""
    log_info "Next steps:"
    log_info "  1. Wait a few minutes for VMs to complete cloud-init setup"
    log_info "  2. Check VM status: ./conductor.py status"
    log_info "  3. Run snail on all VMs: ./conductor.py run"
}

# Run main function
main "$@"
