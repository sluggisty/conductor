#!/bin/bash
# base.sh - Base cloud-init functions
# ===================================

# Source common functions
source "${SCRIPT_DIR}/lib/common.sh"

# Create cloud-init configuration for a VM
create_cloud_init() {
    local vm_name="$1"
    local vm_number="$2"
    local distro="$3"
    local version="$4"
    local output_dir="${CLOUDINIT_DIR}/${vm_name}"
    
    mkdir -p "$output_dir"
    
    # Read SSH public key
    local ssh_pubkey=""
    if [[ -f "${SSH_KEY_PATH}.pub" ]]; then
        ssh_pubkey=$(cat "${SSH_KEY_PATH}.pub")
    fi
    
    # Create meta-data
    cat > "${output_dir}/meta-data" << EOF
instance-id: ${vm_name}
local-hostname: ${vm_name}
EOF
    
    # Generate distribution-specific cloud-init
    # SCRIPT_DIR is set by the calling script (create-vms.sh)
    local cloudinit_dir="${SCRIPT_DIR}/lib/cloudinit"
    case "$distro" in
        fedora)
            source "${cloudinit_dir}/fedora.sh"
            create_fedora_cloud_init "$vm_name" "$version" "$output_dir" "$ssh_pubkey"
            ;;
        debian)
            source "${cloudinit_dir}/debian.sh"
            create_debian_cloud_init "$vm_name" "$version" "$output_dir" "$ssh_pubkey"
            ;;
        ubuntu)
            source "${cloudinit_dir}/ubuntu.sh"
            create_ubuntu_cloud_init "$vm_name" "$version" "$output_dir" "$ssh_pubkey"
            ;;
        centos)
            source "${cloudinit_dir}/centos.sh"
            create_centos_cloud_init "$vm_name" "$version" "$output_dir" "$ssh_pubkey"
            ;;
        rhel)
            source "${cloudinit_dir}/rhel.sh"
            create_rhel_cloud_init "$vm_name" "$version" "$output_dir" "$ssh_pubkey"
            ;;
        suse)
            source "${cloudinit_dir}/suse.sh"
            create_suse_cloud_init "$vm_name" "$version" "$output_dir" "$ssh_pubkey"
            ;;
        *)
            log_error "Unsupported distribution: $distro"
            return 1
            ;;
    esac
}

# Create cloud-init ISO
create_cloud_init_iso() {
    local vm_name="$1"
    # If a full path is passed, use it directly; otherwise construct it
    local cloudinit_dir
    if [[ "$vm_name" == /* ]]; then
        # Full path provided
        cloudinit_dir="$vm_name"
    else
        # Just VM name, construct full path
        cloudinit_dir="${CLOUDINIT_DIR}/${vm_name}"
    fi
    local iso_path="${cloudinit_dir}/cloud-init.iso"
    
    genisoimage -output "$iso_path" \
        -volid cidata \
        -joliet \
        -rock \
        "${cloudinit_dir}/user-data" \
        "${cloudinit_dir}/meta-data" \
        > /dev/null 2>&1
    
    echo "$iso_path"
}

