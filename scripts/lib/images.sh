#!/bin/bash
# images.sh - Image path and checking functions
# ==============================================

# Source common functions
source "${SCRIPT_DIR}/lib/common.sh"

# Get base image path for a distribution and version
get_base_image_path() {
    local distro="$1"
    local version="$2"
    local version_key
    local image_path
    
    case "$distro" in
        fedora)
            image_path="${IMAGE_DIR}/fedora-cloud-base-${version}.qcow2"
            ;;
        debian)
            image_path="${IMAGE_DIR}/debian-cloud-base-${version}.qcow2"
            ;;
        ubuntu)
            version_key="${version//./_}"
            image_path="${IMAGE_DIR}/ubuntu-cloud-base-${version_key}.qcow2"
            ;;
        centos)
            image_path="${IMAGE_DIR}/centos-cloud-base-${version}.qcow2"
            ;;
        rhel)
            # Use actual RHEL image naming pattern: rhel-10.0-x86_64-kvm.qcow2
            image_path="${IMAGE_DIR}/rhel-${version}-x86_64-kvm.qcow2"
            ;;
        suse)
            # Convert version dots to underscores for filename (15.5 -> 15_5)
            # Handle SLES prefix (sles15.5 -> sles_15_5)
            version_key="${version//./_}"
            if [[ "$version" == sles* ]]; then
                version_key="sles_${version_key#sles}"
            fi
            image_path="${IMAGE_DIR}/suse-cloud-base-${version_key}.qcow2"
            ;;
        *)
            log_error "Unknown distribution: $distro"
            return 1
            ;;
    esac
    
    echo "$image_path"
}

# Check if base image exists for a distribution and version
check_base_image() {
    local distro="$1"
    local version="$2"
    local base_image
    base_image=$(get_base_image_path "$distro" "$version")
    
    if [[ ! -f "$base_image" ]]; then
        log_error "Base image not found for ${distro} ${version}: ${base_image}"
        log_info "Run: ./scripts/setup-base-image.sh --distro ${distro} --version ${version}"
        return 1
    fi
    return 0
}




