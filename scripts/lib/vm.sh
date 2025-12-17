#!/bin/bash
# vm.sh - VM creation and management functions
# ============================================

# Source required modules
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/images.sh"
source "${SCRIPT_DIR}/lib/cloudinit/base.sh"

# Create a single VM
create_vm() {
    local vm_name="$1"
    local vm_number="$2"
    local distro="$3"
    local version="$4"
    
    log_step "Creating VM: ${vm_name} (${distro^} ${version})"
    
    # Check if VM already exists
    if sudo virsh list --all --name | grep -q "^${vm_name}$"; then
        log_warning "VM ${vm_name} already exists, skipping..."
        return 0
    fi
    
    # Check base image exists
    if ! check_base_image "$distro" "$version"; then
        return 1
    fi
    
    local base_image
    base_image=$(get_base_image_path "$distro" "$version")
    
    # Create disk from base image
    local disk_path="${IMAGE_DIR}/${vm_name}.qcow2"
    log_info "Creating disk: ${disk_path}"
    sudo cp "$base_image" "$disk_path"
    sudo qemu-img resize "$disk_path" "${DISK_SIZE_GB}G" 2>/dev/null
    
    # Create cloud-init ISO
    log_info "Creating cloud-init configuration..."
    local cloudinit_iso
    create_cloud_init "$vm_name" "$vm_number" "$distro" "$version"
    cloudinit_iso=$(create_cloud_init_iso "$vm_name")
    
    # Determine OS variant
    local os_variant="generic"
    if [[ "$distro" == "fedora" ]]; then
        os_variant="fedora-unknown"
        if [[ "$version" -ge 40 ]]; then
            os_variant="fedora40"
        elif [[ "$version" -ge 38 ]]; then
            os_variant="fedora38"
        elif [[ "$version" -ge 36 ]]; then
            os_variant="fedora36"
        fi
    elif [[ "$distro" == "debian" ]]; then
        case "$version" in
            "12") os_variant="debian12" ;;
            "11") os_variant="debian11" ;;
            "10") os_variant="debian10" ;;
            "9") os_variant="debian9" ;;
            *) os_variant="debian10" ;;
        esac
    elif [[ "$distro" == "ubuntu" ]]; then
        case "$version" in
            "24.04") os_variant="ubuntu24.04" ;;
            "22.04") os_variant="ubuntu22.04" ;;
            "20.04") os_variant="ubuntu20.04" ;;
            "18.04") os_variant="ubuntu18.04" ;;
            *) os_variant="ubuntu22.04" ;;
        esac
    elif [[ "$distro" == "centos" ]]; then
        case "$version" in
            "9") os_variant="centos-stream9" ;;
            "8") os_variant="centos-stream8" ;;
            "7") os_variant="centos7" ;;
            *) os_variant="centos-stream9" ;;
        esac
    elif [[ "$distro" == "rhel" ]]; then
        # Extract major version for OS variant
        local major_version="${version%%.*}"
        case "$major_version" in
            "9") os_variant="rhel9" ;;
            "8") os_variant="rhel8" ;;
            "7") os_variant="rhel7" ;;
            *) os_variant="rhel9" ;;
        esac
    elif [[ "$distro" == "suse" ]]; then
        # SUSE OS variants
        if [[ "$version" == sles* ]]; then
            # SLES
            local sles_version="${version#sles}"
            case "$sles_version" in
                15.5|"15.5") os_variant="sles15sp5" ;;
                15.4|"15.4") os_variant="sles15sp4" ;;
                15.3|"15.3") os_variant="sles15sp3" ;;
                *) os_variant="sles15sp5" ;;
            esac
        elif [[ "$version" == "tumbleweed" ]]; then
            os_variant="opensuse-tumbleweed"
        else
            # openSUSE Leap
            case "$version" in
                15.5|"15.5") os_variant="opensuse15.5" ;;
                15.4|"15.4") os_variant="opensuse15.4" ;;
                15.3|"15.3") os_variant="opensuse15.3" ;;
                15.2|"15.2") os_variant="opensuse15.2" ;;
                *) os_variant="opensuse15.5" ;;
            esac
        fi
    fi
    
    # Create the VM
    log_info "Creating VM with virt-install..."
    sudo virt-install \
        --name "$vm_name" \
        --memory "$MEMORY_MB" \
        --vcpus "$VCPUS" \
        --disk "$disk_path" \
        --disk "${cloudinit_iso},device=cdrom" \
        --os-variant "$os_variant" \
        --network network=default \
        --graphics none \
        --console pty,target_type=serial \
        --import \
        --noautoconsole \
        --wait 0
    
    log_success "VM ${vm_name} created!"
}

# Wait for all VMs to get IP addresses
wait_for_vms() {
    log_info "Waiting for VMs to boot and get IP addresses..."
    
    local max_wait=180
    local waited=0
    local interval=10
    
    # Count total VMs
    local total_vms=0
    IFS=',' read -ra SPECS <<< "$VM_SPECS"
    for spec in "${SPECS[@]}"; do
        local parsed_spec
        parsed_spec=$(parse_vm_spec "$spec")
        IFS=':' read -r distro version <<< "$parsed_spec"
        total_vms=$((total_vms + VM_COUNT_PER_VERSION))
    done
    
    while [[ $waited -lt $max_wait ]]; do
        local ready=0
        
        IFS=',' read -ra SPECS <<< "$VM_SPECS"
        for spec in "${SPECS[@]}"; do
            local parsed_spec
            parsed_spec=$(parse_vm_spec "$spec")
            IFS=':' read -r distro version <<< "$parsed_spec"
            for i in $(seq 1 "$VM_COUNT_PER_VERSION"); do
                local vm_name="${VM_PREFIX}-${distro}-${version}-${i}"
                local ip
                ip=$(sudo virsh domifaddr "$vm_name" 2>/dev/null | \
                    grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | \
                    head -1 || true)
                
                if [[ -n "$ip" ]]; then
                    ready=$((ready + 1))
                fi
            done
        done
        
        if [[ $ready -eq $total_vms ]]; then
            echo ""
            log_success "All ${total_vms} VMs have IP addresses!"
            return 0
        fi
        
        printf "\r${BLUE}[INFO]${NC} %d/%d VMs ready... (%ds elapsed)    " \
            "$ready" "$total_vms" "$waited"
        sleep "$interval"
        waited=$((waited + interval))
    done
    
    echo ""
    log_warning "Timeout waiting for all VMs. Some VMs may not have IP addresses yet."
    log_info "VMs are still booting. Check status with: ./conductor.py status"
    return 0
}

# Display VM information
show_vm_info() {
    echo ""
    echo "=========================================="
    echo "        VM Information Summary"
    echo "=========================================="
    
    printf "%-30s %-18s %-10s\n" "VM Name" "IP Address" "Status"
    printf "%-30s %-18s %-10s\n" \
        "------------------------------" "------------------" "----------"
    
    IFS=',' read -ra SPECS <<< "$VM_SPECS"
    for spec in "${SPECS[@]}"; do
        local parsed_spec
        parsed_spec=$(parse_vm_spec "$spec")
        IFS=':' read -r distro version <<< "$parsed_spec"
        for i in $(seq 1 "$VM_COUNT_PER_VERSION"); do
            local vm_name="${VM_PREFIX}-${distro}-${version}-${i}"
            local status
            status=$(sudo virsh domstate "$vm_name" 2>/dev/null || echo "unknown")
            local ip
            ip=$(sudo virsh domifaddr "$vm_name" 2>/dev/null | \
                grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | \
                head -1 || echo "pending...")
            
            printf "%-30s %-18s %-10s\n" "$vm_name" "$ip" "$status"
        done
    done
    
    echo ""
    echo "SSH Access: ssh -i ${SSH_KEY_PATH} ${VM_USER}@<IP>"
    echo "Console:    sudo virsh console <vm-name>"
    echo ""
}


