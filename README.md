# Conductor - VM Orchestration Tool

VM management and testing tool for managing Linux distribution VMs.

## Overview

Conductor provides tools to:
- List available distributions and their versions
- Check for base images in `/var/lib/libvirt/images`
- Manage VMs across multiple Linux distributions

## Prerequisites

- **Python 3.9+** with pip
- **libvirt/KVM** (for VM management)
- **Access to `/var/lib/libvirt/images`** (see Permissions section below)

### Install Python Dependencies

```bash
cd conductor
pip install -r requirements.txt
```

### Permissions

The script needs to check for base images in `/var/lib/libvirt/images`. If you get permission errors, you have a few options:

1. **Add your user to the libvirt group** (recommended):
   ```bash
   sudo usermod -aG libvirt $USER
   # Log out and back in for changes to take effect
   ```

2. **Run with sudo** (if you have sudo access):
   ```bash
   sudo python3 conductor.py list-versions
   ```

3. **Use the --scan option** which may work better with limited permissions:
   ```bash
   ./conductor.py list-versions --scan
   ```

## Quick Start

### 1. List Available Versions

```bash
# List all available distributions and versions, showing which base images are available
./conductor.py list-versions

# Scan the image directory and show detected images (auto-detects versions from filenames)
./conductor.py list-versions --scan
```

The `list-versions` command will:
- Display tables for each distribution (Fedora, Debian, Ubuntu, CentOS, RHEL, SUSE)
- Show which base images exist in `/var/lib/libvirt/images`
- Indicate subscription requirements for RHEL and SLES

The `--scan` option will:
- Automatically detect available images in the image directory
- Parse image filenames to extract distribution and version information
- Display detected images in a table format

### 2. Create Test VMs

```bash
# Create 5 VMs for Fedora 42 (default)
./conductor.py create

# Create VMs for multiple Fedora versions
./conductor.py create --specs fedora:42,41,40

# Create RHEL VMs
./conductor.py create --specs rhel:10.0,9.4

# Create Ubuntu VMs
./conductor.py create --specs ubuntu:24.04,22.04

# Create mixed distribution VMs
./conductor.py create --specs fedora:42,debian:12,ubuntu:24.04,rhel:10.0

# Create 3 VMs per version with custom resources
./conductor.py create --specs fedora:42,41 --count 3 --memory 1024 --cpus 1

# Create one VM for each distribution that has available base images
# Only creates VMs for distributions/versions that actually have images downloaded
./conductor.py create-all

# Create one VM per distribution with custom resources
./conductor.py create-all --memory 1024 --cpus 1
```

### 3. Check VM Status

```bash
# Show all VMs
./conductor.py status

# Show as JSON
./conductor.py status --json
```

## Supported Distributions

- **Fedora**: versions 42, 41, 40, 39, 38, 37, 36, 35, 34, 33
- **Debian**: versions 12 (Bookworm), 11 (Bullseye), 10 (Buster), 9 (Stretch)
- **Ubuntu**: versions 24.04 LTS, 22.04 LTS, 20.04 LTS, 18.04 LTS
- **CentOS**: versions 9 (Stream), 8 (Stream), 7 (EOL)
- **RHEL**: Comprehensive version support including:
  - **RHEL 10**: 10.1, 10.0, 10 (latest)
  - **RHEL 9**: 9.5, 9.4, 9.3, 9.2, 9.1, 9.0, 9 (latest)
  - **RHEL 8**: 8.11, 8.10, 8.9, 8.8, 8.7, 8.6, 8.5, 8.4, 8.3, 8.2, 8.1, 8.0, 8 (latest)
  - **RHEL 7**: 7.9, 7.8, 7.7, 7.6, 7.5, 7.4, 7.3, 7.2, 7.1, 7.0, 7 (latest)
  - Note: RHEL images require Red Hat subscription
- **SUSE**: openSUSE Leap 15.5, 15.4, 15.3, 15.2, Tumbleweed (rolling), SLES 15.5, 15.4, 15.3 (SLES requires SUSE subscription)

## Base Images

All base images are expected to be in `/var/lib/libvirt/images` with the following naming conventions:

- **Fedora**: `fedora-cloud-base-{version}.qcow2`
- **Debian**: `debian-cloud-base-{version}.qcow2`
- **Ubuntu**: `ubuntu-cloud-base-{version_key}.qcow2` (e.g., `ubuntu-cloud-base-24_04.qcow2`)
- **CentOS**: `centos-cloud-base-{version}.qcow2`
- **RHEL**: `rhel-{version}-x86_64-kvm.qcow2` (e.g., `rhel-10.0-x86_64-kvm.qcow2`, `rhel-9.4-x86_64-kvm.qcow2`)
  - Also supports legacy format: `rhel-cloud-base-{version_key}.qcow2` (e.g., `rhel-cloud-base-10_0.qcow2`)
- **SUSE**: `suse-cloud-base-{version_key}.qcow2` (e.g., `suse-cloud-base-15_5.qcow2`)

## Configuration

Edit `config.yaml` to customize:
- Available distributions and versions
- Image directory path (default: `/var/lib/libvirt/images`)
- VM naming prefix
- Default resources

## Command Reference

### List Versions

| Command | Description |
|---------|-------------|
| `./conductor.py list-versions` | List available distributions and versions with base image status |
| `./conductor.py list-versions --scan` | Scan image directory and auto-detect available images |
| `./conductor.py list-versions --debug` | Show debug information about file checks |

### VM Management

| Command | Description |
|---------|-------------|
| `./conductor.py create` | Create test VMs (default: 5 VMs for Fedora 42) |
| `./conductor.py create --specs fedora:42,41` | Create VMs for specific Fedora versions |
| `./conductor.py create --specs rhel:10.0,9.4` | Create VMs for specific RHEL versions |
| `./conductor.py create --specs ubuntu:24.04,22.04` | Create VMs for specific Ubuntu versions |
| `./conductor.py create --count 3` | Create 3 VMs per version (default: 5) |
| `./conductor.py create --memory 1024 --cpus 1` | Customize VM resources |
| `./conductor.py create-all` | Create one VM for each distribution that has available base images |
| `./conductor.py create-all --memory 1024 --cpus 1` | Customize VM resources for create-all |
| `./conductor.py status` | Show status of all test VMs |
| `./conductor.py status --json` | Show VM status as JSON |

## Directory Structure

```
conductor/
├── README.md           # This file
├── config.yaml         # Configuration file
├── requirements.txt    # Python dependencies
└── conductor.py       # Main CLI tool
```

## License

Same as the main project.

