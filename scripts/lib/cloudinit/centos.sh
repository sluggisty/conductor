#!/bin/bash
# centos.sh - CentOS-specific cloud-init generation
# Source common functions
source "${SCRIPT_DIR}/lib/common.sh"


create_centos_cloud_init() {
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
  - name: root
    lock_passwd: false
    plain_text_passwd: ${VM_PASSWORD}
    shell: /bin/bash
  
  # Create conductor user
  - name: ${VM_USER}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: wheel, systemd-journal
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

# Install required packages
packages:
  - python3
  - python3-pip
  - git
  - curl
  - vim
  - lsof
  - lshw
  - pciutils
  - usbutils

# Run commands after boot
runcmd:
  # Ensure SSH service is enabled and started
  - systemctl enable sshd || systemctl enable ssh || true
  - systemctl start sshd || systemctl start ssh || true
  
  # Configure firewall to allow SSH (CentOS uses firewalld)
  - firewall-cmd --permanent --add-service=ssh || true
  - firewall-cmd --reload || true
  # If firewalld is not available, try iptables (older CentOS)
  - iptables -I INPUT -p tcp --dport 22 -j ACCEPT || true
  - service iptables save || true
  
  # Update system
  - dnf update -y || yum update -y || true
  
  # Install python3-venv (package name varies by CentOS version)
  - dnf install -y python3-virtualenv || \
      yum install -y python3-virtualenv || \
      python3 -m pip install virtualenv || \
      true
  
  # Install optional security packages
  - dnf install -y openscap-scanner scap-security-guide || \
      yum install -y openscap-scanner scap-security-guide || \
      echo "Some optional packages not available, continuing..."
  
  # Install trivy using official install script
  - curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin || echo "Trivy installation failed, continuing..."
  
  # Install snail-core from PyPI
  - python3 -m venv /opt/snail-core/venv || python3 -m virtualenv /opt/snail-core/venv
  - /opt/snail-core/venv/bin/pip install --upgrade pip
  - /opt/snail-core/venv/bin/pip install snail-core
  
  # Create snail-core config directory
  - mkdir -p /etc/snail-core
  
  # Create configuration file (using base64 to avoid YAML parsing issues)
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
  Snail Core VM ${vm_name} (CentOS ${version}) is ready!
  Setup took \$UPTIME seconds.
EOF
}
