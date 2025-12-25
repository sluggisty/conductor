#!/bin/bash
# suse.sh - SUSE-specific cloud-init generation
# Source common functions
source "${SCRIPT_DIR}/lib/common.sh"


create_suse_cloud_init() {
    local vm_name="$1"
    local version="$2"
    local output_dir="$3"
    local ssh_pubkey="$4"
    
    # SUSE uses zypper as package manager
    local package_manager="zypper"
    
    cat > "${output_dir}/user-data" << EOF
#cloud-config
hostname: ${vm_name}
fqdn: ${vm_name}.local

# User configuration
users:
  - name: ${VM_USER}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: wheel, users
    shell: /bin/bash
    lock_passwd: false
    ssh_authorized_keys:
      - ${ssh_pubkey}

# Set password (for console access)
chpasswd:
  list: |
    ${VM_USER}:${VM_PASSWORD}
  expire: false

# Enable SSH password auth (backup)
ssh_pwauth: true

# Install required packages
packages:
  - python39
  - python39-pip
  - python39-virtualenv
  - git
  - curl
  - vim
  - lsof
  - lshw
  - pciutils
  - usbutils

# Run commands after boot
runcmd:
  # Update system
  - ${package_manager} refresh || true
  - ${package_manager} update -y || true
  
  # Install optional security packages (may not be available in all versions)
  - ${package_manager} install -y openscap || echo "openscap not available, continuing..."
  - ${package_manager} install -y scap-security-guide || echo "scap-security-guide not available, continuing..."
  
  # Install trivy using official install script
  - curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin || echo "Trivy installation failed, continuing..."
  
  # Install snail-core from PyPI
  # Note: snail-core requires Python >=3.9
  # SUSE 15.2 only has Python 3.6, which is too old
  # SUSE 15.5+ has Python 3.9+ and will work
  - |
    # Check Python version first
    PYTHON_VERSION=\$(python3 --version 2>&1 | awk '{print \$2}' | cut -d. -f1,2)
    PYTHON_MAJOR=\$(echo \$PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=\$(echo \$PYTHON_VERSION | cut -d. -f2)
    
    # Determine which Python to use (prefer 3.9+)
    if command -v python3.9 >/dev/null 2>&1; then
      PYTHON_CMD=python3.9
    elif command -v python3.10 >/dev/null 2>&1; then
      PYTHON_CMD=python3.10
    elif command -v python3.11 >/dev/null 2>&1; then
      PYTHON_CMD=python3.11
    elif command -v python3.12 >/dev/null 2>&1; then
      PYTHON_CMD=python3.12
    else
      PYTHON_CMD=python3
    fi
    
    PYTHON_ACTUAL_VERSION=\$(\$PYTHON_CMD --version 2>&1 | awk '{print \$2}')
    PYTHON_ACTUAL_MAJOR=\$(echo \$PYTHON_ACTUAL_VERSION | cut -d. -f1)
    PYTHON_ACTUAL_MINOR=\$(echo \$PYTHON_ACTUAL_VERSION | cut -d. -f2)
    
    echo "Detected Python version: \$PYTHON_ACTUAL_VERSION"
    
    # Check if Python version is sufficient (>=3.9)
    if [ "\$PYTHON_ACTUAL_MAJOR" -lt 3 ] || ([ "\$PYTHON_ACTUAL_MAJOR" -eq 3 ] && [ "\$PYTHON_ACTUAL_MINOR" -lt 9 ]); then
      echo "ERROR: snail-core requires Python >=3.9, but this system has Python \$PYTHON_ACTUAL_VERSION"
      echo "SUSE ${version} (openSUSE Leap 15.2) only provides Python 3.6, which is too old."
      echo "Recommendation: Use SUSE 15.5 or newer (has Python 3.9+)"
      echo "Creating marker file to indicate installation failure"
      mkdir -p /var/lib/snail-core
      echo "Python version \$PYTHON_ACTUAL_VERSION is too old. Requires >=3.9" > /var/lib/snail-core/.install-failed
      exit 0  # Don't fail cloud-init, just skip snail-core installation
    fi
    
    echo "Using Python: \$PYTHON_CMD (\$PYTHON_ACTUAL_VERSION)"
    \$PYTHON_CMD -m venv /opt/snail-core/venv || \$PYTHON_CMD -m virtualenv /opt/snail-core/venv || true
  - /opt/snail-core/venv/bin/pip install --upgrade pip
  - |
    # Install snail-core
    if /opt/snail-core/venv/bin/pip install snail-core 2>&1; then
      echo "snail-core installed successfully"
    else
      echo "ERROR: Failed to install snail-core"
      mkdir -p /var/lib/snail-core
      echo "pip install failed" > /var/lib/snail-core/.install-failed
    fi
  
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
  Snail Core VM ${vm_name} (SUSE ${version}) is ready!
  Setup took \$UPTIME seconds.
EOF
}
