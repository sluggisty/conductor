#!/bin/bash
# ubuntu.sh - Ubuntu-specific cloud-init generation
# Source common functions
source "${SCRIPT_DIR}/lib/common.sh"


create_ubuntu_cloud_init() {
    local vm_name="$1"
    local version="$2"
    local output_dir="$3"
    local ssh_pubkey="$4"
    
    cat > "${output_dir}/user-data" << EOF
#cloud-config
hostname: ${vm_name}
fqdn: ${vm_name}.local

# Enable root login for console access (useful during cloud-init)
disable_root: false

# User configuration
users:
  # Create root user with password for console access
  # IMPORTANT: For Ubuntu 20.04/22.04, we need to set root password explicitly
  - name: root
    lock_passwd: false
    plain_text_passwd: ${VM_PASSWORD}
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
  
  # Create conductor user
  - name: ${VM_USER}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo, adm, systemd-journal
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: ${VM_PASSWORD}
    ssh_authorized_keys:
      - ${ssh_pubkey}

# Set password (for console access) - backup method
chpasswd:
  list: |
    root:${VM_PASSWORD}
    ${VM_USER}:${VM_PASSWORD}
  expire: false

# Enable SSH password auth (backup)
ssh_pwauth: true

# Ensure SSH service is enabled
ssh:
  emit_keys_to_console: false
  allow_public_ssh_keys: true
  disable_root: false

# Network configuration - REMOVED (using runcmd instead for better Ubuntu 20.04/22.04 compatibility)
# Ubuntu 20.04/22.04 have issues with cloud-init's network: section
# We'll configure networking manually in runcmd instead

# Install required packages
packages:
  - python3
  - python3-pip
  - python3-venv
  - git
  - curl
  - vim
  - lsof
  - lshw
  - pciutils
  - usbutils

# Run commands after boot
runcmd:
  # Network configuration - manual setup for Ubuntu 20.04/22.04 compatibility
  # This runs FIRST to ensure network is up before other services
  # Write network status to a file for debugging
  - echo "Starting network configuration..." > /tmp/network-setup.log 2>&1
  - |
    # Find the first non-loopback interface and bring it up
    for iface in \$(ls /sys/class/net/ | grep -v lo); do
      if [ -n "\$iface" ] && [ -d "/sys/class/net/\$iface" ]; then
        echo "Found interface: \$iface" >> /tmp/network-setup.log
        # Bring interface up
        ip link set up dev \$iface 2>&1 | tee -a /tmp/network-setup.log || true
        # Try dhclient (Ubuntu/Debian) - with longer timeout
        timeout 30 dhclient -v \$iface 2>&1 | tee -a /tmp/network-setup.log || true
        # Also try with -1 flag for one-shot mode
        timeout 30 dhclient -1 -v \$iface 2>&1 | tee -a /tmp/network-setup.log || true
        # Check if we got an IP
        if ip addr show \$iface | grep -q "inet "; then
          echo "SUCCESS: Interface \$iface has IP address" >> /tmp/network-setup.log
          ip addr show \$iface >> /tmp/network-setup.log
          break
        else
          echo "FAILED: Interface \$iface did not get IP address" >> /tmp/network-setup.log
        fi
      fi
    done
  # Ensure network services are running
  - systemctl restart systemd-networkd 2>&1 | tee -a /tmp/network-setup.log || systemctl restart NetworkManager 2>&1 | tee -a /tmp/network-setup.log || true
  - sleep 5
  # Verify network is up and show IP
  - ip addr show >> /tmp/network-setup.log 2>&1 || true
  - echo "Network setup complete. Status:" >> /tmp/network-setup.log
  - cat /tmp/network-setup.log || true
  
  # Ensure SSH service is enabled and started
  - systemctl enable ssh || systemctl enable sshd || true
  - systemctl start ssh || systemctl start sshd || true
  - systemctl restart ssh || systemctl restart sshd || true
  
  # Update system
  - apt-get update -y || true
  - apt-get upgrade -y || true
  
  # Install optional security packages
  - apt-get install -y openscap-scanner scap-security-guide || echo "Some optional packages not available, continuing..."
  
  # Install trivy using official install script
  - curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin || echo "Trivy installation failed, continuing..."
  
  # Install snail-core from PyPI
  - python3 -m venv /opt/snail-core/venv
  - /opt/snail-core/venv/bin/pip install --upgrade pip
  - /opt/snail-core/venv/bin/pip install snail-core
  
  # Create snail-core config directory
  - mkdir -p /etc/snail-core
  
  # Create configuration file
  - |
    cat > /etc/snail-core/config.yaml << 'EOF2'
    api:
      endpoint: ${SNAIL_API_ENDPOINT}
      api_key: ${SNAIL_API_KEY}
      timeout: 30
      retries: 3
    auth:
      api_key: ${SNAIL_API_KEY}
    collection:
      enabled_collectors: []
      disabled_collectors: []
      timeout: 300
    output:
      dir: /var/lib/snail-core
      keep_local: true
      compress: true
    logging:
      level: INFO
    EOF2
  
  # Create systemd service for snail
  - |
    cat > /etc/systemd/system/snail-core.service << 'SNAILSERVICE'
    [Unit]
    Description=Snail Core System Collection
    After=network-online.target
    Wants=network-online.target
    
    [Service]
    Type=oneshot
    ExecStart=/opt/snail-core/venv/bin/snail run
    Environment=SNAIL_API_KEY=${SNAIL_API_KEY}
    
    [Install]
    WantedBy=multi-user.target
    SNAILSERVICE
  
  # Create timer to run periodically (every 5 minutes for testing)
  - |
    cat > /etc/systemd/system/snail-core.timer << 'SNAILTIMER'
    [Unit]
    Description=Run Snail Core periodically
    
    [Timer]
    OnBootSec=2min
    OnUnitActiveSec=5min
    
    [Install]
    WantedBy=timers.target
    SNAILTIMER
  
  # Create output directory
  - mkdir -p /var/lib/snail-core
  
  # Create symlink for easy access
  - ln -sf /opt/snail-core/venv/bin/snail /usr/local/bin/snail
  
  # Enable and start the timer
  - systemctl daemon-reload
  - systemctl enable snail-core.timer
  - systemctl start snail-core.timer
  
  # Run snail once immediately
  - SNAIL_API_KEY=${SNAIL_API_KEY} /opt/snail-core/venv/bin/snail run || true
  
  # Mark setup complete
  - touch /var/lib/snail-core/.setup-complete

# Write files
write_files:
  - path: /etc/profile.d/snail.sh
    content: |
      export SNAIL_API_KEY="${SNAIL_API_KEY}"
      alias snail="/opt/snail-core/venv/bin/snail"
    permissions: '0644'

final_message: |
  Snail Core VM ${vm_name} (Ubuntu ${version}) is ready!
  Setup took \$UPTIME seconds.
EOF
}
