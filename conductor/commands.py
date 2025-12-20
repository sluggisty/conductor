"""
CLI command implementations.

Contains all the Click command handlers for the Conductor CLI.
"""

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from conductor.config import SCRIPTS_DIR, load_config
import yaml
from conductor.images import check_image_exists, get_base_image_path, scan_available_images
from conductor.utils import run_command
from conductor.vms import (
    check_cloud_init_complete,
    get_available_distro_versions,
    get_running_vms,
    get_stopped_vms,
    get_vm_ip,
    get_vm_list,
    get_vm_state,
)

console = Console()


def list_versions(scan: bool, debug: bool) -> None:
    """List available distributions and their versions."""
    config = load_config()
    distributions = config.get("vms", {}).get("distributions", {})
    image_dir = config.get("host", {}).get("image_dir", "/var/lib/libvirt/images")
    
    # If scan is requested, show detected images
    if scan:
        console.print("\n[bold]Scanning image directory for available images...[/]\n")
        detected = scan_available_images(image_dir)
        
        for distro, versions in detected.items():
            if versions:
                table = Table(title=f"Detected {distro.capitalize()} Images")
                table.add_column("Version", style="cyan")
                table.add_column("Image File", style="green")
                
                for version in versions:
                    base_image = get_base_image_path(distro, version, image_dir)
                    if base_image:
                        img_file = base_image.name
                    else:
                        img_file = "unknown"
                    
                    table.add_row(version, img_file)
                
                console.print(table)
                console.print()
        
        console.print(f"[dim]Image directory: {image_dir}[/]\n")
        return
    
    console.print()
    
    # Show Fedora versions
    if "fedora" in distributions:
        _show_distro_versions(
            "fedora",
            distributions["fedora"].get("available_versions", {}),
            image_dir,
            "Available Fedora Versions"
        )
    
    # Show Debian versions
    if "debian" in distributions:
        _show_distro_versions(
            "debian",
            distributions["debian"].get("available_versions", {}),
            image_dir,
            "Available Debian Versions"
        )
    
    # Show Ubuntu versions
    if "ubuntu" in distributions:
        _show_ubuntu_versions(
            distributions["ubuntu"].get("available_versions", {}),
            image_dir
        )
    
    # Show CentOS versions
    if "centos" in distributions:
        _show_distro_versions(
            "centos",
            distributions["centos"].get("available_versions", {}),
            image_dir,
            "Available CentOS Versions"
        )
    
    # Show RHEL versions
    if "rhel" in distributions:
        _show_rhel_versions(
            distributions["rhel"].get("available_versions", {}),
            image_dir,
            debug
        )
    
    # Show SUSE versions
    if "suse" in distributions:
        _show_suse_versions(
            distributions["suse"].get("available_versions", {}),
            image_dir
        )
    
    console.print(f"[dim]Base images directory: {image_dir}[/]")
    console.print("[dim]✓ = Image exists, ✗ = Image not found[/]")
    console.print("")


def _show_distro_versions(
    distro: str,
    versions: dict,
    image_dir: str,
    title: str
) -> None:
    """Show versions for a simple numeric distro (Fedora, Debian, CentOS)."""
    table = Table(title=title)
    table.add_column("Version", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Base Image", justify="center")
    
    # Sort by version number (handle both int and string keys)
    def sort_key(item):
        version = item[0]
        if isinstance(version, int):
            return version
        elif isinstance(version, str) and version.isdigit():
            return int(version)
        else:
            return 0
    
    for version, name in sorted(versions.items(), key=sort_key, reverse=True):
        base_image = get_base_image_path(distro, str(version), image_dir)
        exists = check_image_exists(base_image) if base_image else False
        status = "[green]✓[/]" if exists else "[red]✗[/]"
        table.add_row(str(version), name, status)
    
    console.print(table)
    console.print()


def _show_ubuntu_versions(versions: dict, image_dir: str) -> None:
    """Show Ubuntu versions (handles version numbers like 24.04)."""
    table = Table(title="Available Ubuntu Versions")
    table.add_column("Version", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Base Image", justify="center")
    
    # Sort Ubuntu versions (they're like "24.04", "22.04", etc.)
    def ubuntu_sort_key(item):
        version = item[0]
        if isinstance(version, str) and "." in version:
            parts = version.split(".")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return int(parts[0]) * 100 + int(parts[1])
        return 0
    
    for version, name in sorted(versions.items(), key=ubuntu_sort_key, reverse=True):
        base_image = get_base_image_path("ubuntu", str(version), image_dir)
        exists = check_image_exists(base_image) if base_image else False
        status = "[green]✓[/]" if exists else "[red]✗[/]"
        table.add_row(str(version), name, status)
    
    console.print(table)
    console.print()


def _show_rhel_versions(versions: dict, image_dir: str, debug: bool) -> None:
    """Show RHEL versions with multiple naming pattern support."""
    table = Table(title="Available RHEL Versions")
    table.add_column("Version", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Base Image", justify="center")
    table.add_column("Note", style="yellow")
    
    # Sort RHEL versions
    # Examples: "10.1", "10.0", "10", "9.4", "9.3", "9", "8.10", "8", "7.9", "7"
    def rhel_sort_key(item):
        version = item[0]
        if isinstance(version, str):
            if "." in version:
                # Minor release: "10.1" -> 10001, "9.4" -> 904, "8.10" -> 810
                parts = version.split(".")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    return int(parts[0]) * 1000 + int(parts[1])
            elif version.isdigit():
                # Major version: "10" -> 10000, "9" -> 9000
                return int(version) * 1000
        return 0
    
    for version, name in sorted(versions.items(), key=rhel_sort_key, reverse=True):
        exists = False
        base_image = None
        
        # Try the actual naming pattern first: rhel-10.0-x86_64-kvm.qcow2
        actual_image = Path(image_dir) / f"rhel-{version}-x86_64-kvm.qcow2"
        if check_image_exists(actual_image):
            exists = True
            base_image = actual_image
        
        # Try legacy naming pattern if the actual one doesn't exist
        if not exists:
            version_key = str(version).replace(".", "_")
            legacy_image = Path(image_dir) / f"rhel-cloud-base-{version_key}.qcow2"
            if check_image_exists(legacy_image):
                exists = True
                base_image = legacy_image
        
        # Try without underscores (e.g., rhel-cloud-base-10.1.qcow2)
        if not exists:
            alt_image = Path(image_dir) / f"rhel-cloud-base-{version}.qcow2"
            if check_image_exists(alt_image):
                exists = True
                base_image = alt_image
        
        status = "[green]✓[/]" if exists else "[red]✗[/]"
        note = "[yellow]Requires subscription[/]" if not exists else ""
        
        if debug:
            img_name = base_image.name if base_image else "none"
            console.print(f"[dim]Debug: {version} -> {img_name} exists={exists}[/]")
        
        table.add_row(str(version), name, status, note)
    
    console.print(table)
    console.print()


def _show_suse_versions(versions: dict, image_dir: str) -> None:
    """Show SUSE versions."""
    table = Table(title="Available SUSE Versions")
    table.add_column("Version", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Base Image", justify="center")
    table.add_column("Note", style="yellow")
    
    # Sort SUSE versions
    def suse_sort_key(item):
        version = item[0]
        if isinstance(version, str):
            if version.startswith("sles"):
                # SLES: sles15.5 -> 15005, sles15.4 -> 15004
                num = version[4:].replace(".", "")
                if num.isdigit():
                    return 20000 + int(num)  # SLES after openSUSE
            elif version == "tumbleweed":
                return 30000  # Tumbleweed last
            elif "." in version:
                # openSUSE Leap: 15.5 -> 1505, 15.4 -> 1504
                parts = version.split(".")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    return int(parts[0]) * 100 + int(parts[1])
        return 0
    
    for version, name in sorted(versions.items(), key=suse_sort_key, reverse=True):
        base_image = get_base_image_path("suse", str(version), image_dir)
        exists = check_image_exists(base_image) if base_image else False
        status = "[green]✓[/]" if exists else "[red]✗[/]"
        note = ""
        if isinstance(version, str) and version.startswith("sles") and not exists:
            note = "[yellow]Requires subscription[/]"
        table.add_row(str(version), name, status, note)
    
    console.print(table)
    console.print()


def create_vms(
    distro: str,
    versions: str,
    specs: str,
    count: int,
    memory: int,
    cpus: int
) -> None:
    """Create test VMs for specified distributions and versions."""
    console.print(Panel.fit(
        "[bold blue]Creating Conductor Test VMs[/]",
        border_style="blue"
    ))
    
    config = load_config()
    default_distro = config.get("vms", {}).get("default_distribution", "fedora")
    
    # Build VM specs
    vm_specs = []
    
    if specs:
        # Use explicit specs format: "fedora:42,debian:12"
        vm_specs = [s.strip() for s in specs.split(",")]
    elif versions:
        # Use versions with optional distro
        distro_to_use = distro or default_distro
        version_list = [v.strip() for v in versions.split(",")]
        vm_specs = [f"{distro_to_use}:{v}" for v in version_list]
    else:
        # Use defaults from config
        default_versions = config.get("vms", {}).get("default_versions", ["fedora:42"])
        vm_specs = [str(v) for v in default_versions]
    
    console.print(f"\n[dim]VM specs: {', '.join(vm_specs)}[/]")
    console.print(f"[dim]VMs per version: {count}[/]\n")
    
    # Check for base images
    console.print("[dim]Checking base images...[/]")
    image_dir = config.get("host", {}).get("image_dir", "/var/lib/libvirt/images")
    missing_images = []
    
    for spec in vm_specs:
        # Parse spec (format: "distro:version" or just "version")
        if ":" in spec:
            spec_distro, spec_version = spec.split(":", 1)
        else:
            spec_distro = default_distro
            spec_version = spec
        
        # Get base image path based on distribution
        base_image = get_base_image_path(
            spec_distro,
            spec_version,
            image_dir
        )
        
        if base_image is None:
            console.print(f"[red]Unknown distribution: {spec_distro}[/]")
            sys.exit(1)
        
        if not check_image_exists(base_image):
            missing_images.append((spec_distro, spec_version))
            console.print(
                f"[yellow]Base image missing for {spec_distro} {spec_version}[/]"
            )
            console.print(f"[dim]Expected: {base_image.name}[/]")
    
    if missing_images:
        missing_list = ', '.join([f'{d}:{v}' for d, v in missing_images])
        console.print(f"\n[red]Missing base images for: {missing_list}[/]")
        console.print("[yellow]Please download the required base images first.[/]")
        console.print(
            "[dim]You can use the setup-base-image.sh script or download manually.[/]"
        )
        sys.exit(1)
    
    # Create VMs
    total_vms = len(vm_specs) * count
    console.print(
        f"\n[dim]Creating {total_vms} VMs ({count} per version)...[/]\n"
    )
    
    # Get configuration values from config file
    host_config = config.get("host", {})
    vms_config = config.get("vms", {})
    
    # Image and cloud-init directories
    image_dir_config = host_config.get(
        "image_dir",
        "/var/lib/libvirt/images"
    )
    cloudinit_dir_config = host_config.get(
        "cloudinit_dir",
        "/tmp/conductor-test-cloudinit"
    )
    
    # VM naming and credentials
    vm_prefix = vms_config.get("name_prefix", "conductor-test")
    vm_user = vms_config.get("username", "conductor")
    vm_password = vms_config.get("password", "conductortest123")
    ssh_key_default = "~/.ssh/conductor-test-key"
    ssh_key_path = os.path.expanduser(
        vms_config.get("ssh_key_path", ssh_key_default)
    )
    
    env = os.environ.copy()
    env["VM_SPECS"] = ",".join(vm_specs)
    env["VM_COUNT_PER_VERSION"] = str(count)
    env["MEMORY_MB"] = str(memory)
    env["VCPUS"] = str(cpus)
    env["IMAGE_DIR"] = image_dir_config
    env["CLOUDINIT_DIR"] = cloudinit_dir_config
    env["VM_PREFIX"] = vm_prefix
    env["VM_USER"] = vm_user
    env["VM_PASSWORD"] = vm_password
    env["SSH_KEY_PATH"] = ssh_key_path
    
    result = run_command(
        ["bash", str(SCRIPTS_DIR / "create-vms.sh")],
        capture=False,
        check=False,  # Don't fail on non-zero exit
        env=env
    )
    
    # Check if VMs were actually created
    vms = get_vm_list()
    if len(vms) > 0:
        console.print(f"\n[green]✓ {len(vms)} VMs created![/]")
        console.print(
            "[dim]Note: VMs may take a few minutes to boot and get IP addresses.[/]"
        )
        console.print("[dim]Check status with: ./conductor.py status[/]")
    else:
        console.print("[red]Failed to create VMs[/]")
        sys.exit(1)


def show_status(as_json: bool, check_cloudinit: bool) -> None:
    """
    Show status of all test VMs.
    
    Args:
        as_json: Output as JSON
        check_cloudinit: Check cloud-init completion status (slower but more informative)
    """
    vms = get_vm_list()
    
    if not vms:
        console.print("[yellow]No test VMs found[/]")
        return
    
    config = load_config()
    vms_config = config.get("vms", {})
    vm_user = vms_config.get("username", "conductor")
    ssh_key_default = "~/.ssh/conductor-test-key"
    ssh_key_path = os.path.expanduser(
        vms_config.get("ssh_key_path", ssh_key_default)
    )
    
    if as_json:
        import json
        data = []
        for vm in vms:
            vm_info = {"name": vm}
            state = get_vm_state(vm)
            vm_info["state"] = state
            
            if state == "running":
                ip = get_vm_ip(vm)
                vm_info["ip"] = ip
                
                if check_cloudinit and ip:
                    cloudinit_ready = check_cloud_init_complete(vm, ip, ssh_key_path, vm_user)
                    vm_info["cloud_init_ready"] = cloudinit_ready
            
            data.append(vm_info)
        
        console.print_json(json.dumps(data))
        return
    
    console.print()
    table = Table(title="Conductor Test VMs")
    table.add_column("VM Name", style="cyan")
    table.add_column("State", style="yellow")
    table.add_column("IP Address", style="green")
    
    if check_cloudinit:
        table.add_column("Cloud-Init", justify="center", style="blue")
    
    cloudinit_ready_count = 0
    cloudinit_not_ready_count = 0
    
    for vm in vms:
        state = get_vm_state(vm)
        state_display = state.capitalize() if state != "unknown" else "[dim]unknown[/]"
        
        if state == "running":
            ip = get_vm_ip(vm)
            ip_display = ip if ip else "[dim]pending...[/]"
            
            if check_cloudinit:
                if ip:
                    cloudinit_ready = check_cloud_init_complete(vm, ip, ssh_key_path, vm_user)
                    if cloudinit_ready:
                        cloudinit_display = "[green]✓ Ready[/]"
                        cloudinit_ready_count += 1
                    else:
                        cloudinit_display = "[yellow]⏳ Running...[/]"
                        cloudinit_not_ready_count += 1
                else:
                    cloudinit_display = "[dim]No IP[/]"
                
                table.add_row(vm, state_display, ip_display, cloudinit_display)
            else:
                table.add_row(vm, state_display, ip_display)
        else:
            if check_cloudinit:
                table.add_row(vm, state_display, "[dim]—[/]", "[dim]—[/]")
            else:
                table.add_row(vm, state_display, "[dim]—[/]")
    
    console.print(table)
    
    if check_cloudinit:
        running_vms = [v for v in vms if get_vm_state(v) == "running"]
        console.print(f"\n[dim]Total: {len(vms)} VMs[/]")
        console.print(f"[dim]Running: {len(running_vms)}[/]")
        if running_vms:
            console.print(f"[green]Cloud-init ready: {cloudinit_ready_count}[/]")
            if cloudinit_not_ready_count > 0:
                console.print(f"[yellow]Cloud-init still running: {cloudinit_not_ready_count}[/]")
    else:
        console.print(f"\n[dim]Total: {len(vms)} VMs[/]")
        console.print(f"[dim]Use --check-cloudinit to see cloud-init status[/]")


def create_all_vms(memory: int, cpus: int) -> None:
    """Create one VM for each distribution that has available base images."""
    console.print(Panel.fit(
        "[bold blue]Creating One VM Per Available Distribution[/]",
        border_style="blue"
    ))
    
    config = load_config()
    image_dir = config.get("host", {}).get("image_dir", "/var/lib/libvirt/images")
    
    # Get available distributions with their first available version
    console.print("\n[dim]Checking for available base images...[/]\n")
    available_distros = get_available_distro_versions(config, image_dir)
    
    if not available_distros:
        console.print(
            "[red]No distributions with available base images found[/]"
        )
        console.print(
            "[yellow]Please download base images first using "
            "list-versions to see what's available.[/]"
        )
        sys.exit(1)
    
    # Build VM specs from available distributions
    vm_specs = []
    for distro_name, version in sorted(available_distros.items()):
        vm_specs.append(f"{distro_name}:{version}")
        console.print(f"[green]✓[/] {distro_name}: {version}")
    
    console.print(f"\n[dim]VM specs: {', '.join(vm_specs)}[/]")
    console.print(
        f"[dim]VMs to create: {len(vm_specs)} "
        "(one per available distribution)[/]\n"
    )
    
    # Create VMs (one per distribution)
    console.print(f"[dim]Creating {len(vm_specs)} VMs...[/]\n")
    
    # Get configuration values from config file
    host_config = config.get("host", {})
    vms_config = config.get("vms", {})
    
    # Image and cloud-init directories
    image_dir_config = host_config.get(
        "image_dir",
        "/var/lib/libvirt/images"
    )
    cloudinit_dir_config = host_config.get(
        "cloudinit_dir",
        "/tmp/conductor-test-cloudinit"
    )
    
    # VM naming and credentials
    vm_prefix = vms_config.get("name_prefix", "conductor-test")
    vm_user = vms_config.get("username", "conductor")
    vm_password = vms_config.get("password", "conductortest123")
    ssh_key_default = "~/.ssh/conductor-test-key"
    ssh_key_path = os.path.expanduser(
        vms_config.get("ssh_key_path", ssh_key_default)
    )
    
    env = os.environ.copy()
    env["VM_SPECS"] = ",".join(vm_specs)
    env["VM_COUNT_PER_VERSION"] = "1"  # One VM per distribution
    env["MEMORY_MB"] = str(memory)
    env["VCPUS"] = str(cpus)
    env["IMAGE_DIR"] = image_dir_config
    env["CLOUDINIT_DIR"] = cloudinit_dir_config
    env["VM_PREFIX"] = vm_prefix
    env["VM_USER"] = vm_user
    env["VM_PASSWORD"] = vm_password
    env["SSH_KEY_PATH"] = ssh_key_path
    
    result = run_command(
        ["bash", str(SCRIPTS_DIR / "create-vms.sh")],
        capture=False,
        check=False,  # Don't fail on non-zero exit
        env=env
    )
    
    # Check if VMs were actually created
    vms = get_vm_list()
    if len(vms) > 0:
        console.print(f"\n[green]✓ {len(vms)} VMs created![/]")
        console.print(
            "[dim]Note: VMs may take a few minutes to boot and get IP addresses.[/]"
        )
        console.print("[dim]Check status with: ./conductor.py status[/]")
    else:
        console.print("[red]Failed to create VMs[/]")
        sys.exit(1)


def run_snail_on_vms(
    parallel: bool,
    timeout: int,
    upload_url: str | None
) -> None:
    """
    Run snail-core on all running VMs.
    
    Args:
        parallel: Whether to run commands in parallel
        timeout: SSH command timeout in seconds
        upload_url: Optional upload URL to pass to snail-core
    """
    console.print(Panel.fit(
        "[bold blue]Running snail-core on VMs[/]",
        border_style="blue"
    ))
    
    config = load_config()
    vms_config = config.get("vms", {})
    vm_user = vms_config.get("username", "conductor")
    ssh_key_default = "~/.ssh/conductor-test-key"
    ssh_key_path = os.path.expanduser(
        vms_config.get("ssh_key_path", ssh_key_default)
    )
    
    # Verify SSH key exists
    if not os.path.exists(ssh_key_path):
        console.print(f"[red]SSH key not found: {ssh_key_path}[/]")
        console.print("[yellow]The SSH key should be generated during VM creation.[/]")
        console.print("[yellow]If VMs were created manually, ensure the key exists.[/]")
        sys.exit(1)
    
    # Check key permissions (should be 600)
    key_stat = os.stat(ssh_key_path)
    if key_stat.st_mode & 0o077 != 0:
        console.print(f"[yellow]Warning: SSH key has insecure permissions[/]")
        console.print(f"[dim]Run: chmod 600 {ssh_key_path}[/]")
    
    # Get running VMs
    running_vms = get_running_vms()
    
    if not running_vms:
        console.print("[yellow]No running VMs found[/]")
        return
    
    console.print(f"\n[dim]Found {len(running_vms)} running VM(s)[/]\n")
    
    # Get IP addresses for all VMs
    vm_ips = {}
    console.print("[dim]Getting IP addresses...[/]")
    for vm_name in running_vms:
        ip = get_vm_ip(vm_name)
        if ip:
            vm_ips[vm_name] = ip
            console.print(f"[green]✓[/] {vm_name}: {ip}")
        else:
            console.print(f"[yellow]⚠[/] {vm_name}: No IP address found")
    
    if not vm_ips:
        console.print("[red]No VMs with IP addresses found[/]")
        return
    
    console.print(f"\n[dim]Running snail-core on {len(vm_ips)} VM(s)...[/]\n")
    
    # First, verify SSH connectivity and wait for cloud-init to complete
    console.print("[dim]Verifying SSH connectivity (waiting for cloud-init to complete)...[/]")
    ssh_ready = {}
    max_wait_time = 300  # 5 minutes max wait
    check_interval = 10  # Check every 10 seconds
    max_attempts = max_wait_time // check_interval
    
    for vm_name, ip in vm_ips.items():
        console.print(f"[cyan]Checking {vm_name} ({ip})...[/]")
        
        # Try a simple SSH command to check if key is authorized
        test_cmd = [
            "ssh",
            "-i", ssh_key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no",
            "-o", "PubkeyAuthentication=yes",
            "-q",  # Quiet mode
            f"{vm_user}@{ip}",
            "echo 'SSH ready'"
        ]
        
        import time
        ssh_connected = False
        for attempt in range(max_attempts):
            test_result = run_command(test_cmd, capture=True, check=False, timeout=10)
            if test_result.returncode == 0:
                ssh_ready[vm_name] = ip
                ssh_connected = True
                if attempt == 0:
                    console.print(f"[green]✓[/] {vm_name}: SSH ready")
                else:
                    console.print(f"[green]✓[/] {vm_name}: SSH ready (after {attempt * check_interval}s)")
                break
            else:
                if attempt == 0:
                    console.print(f"[dim]  → Waiting for cloud-init to complete...[/]")
                elif attempt % 3 == 0:  # Show progress every 30 seconds
                    console.print(f"[dim]  → Still waiting... ({attempt * check_interval}s elapsed)[/]")
            
            if attempt < max_attempts - 1:
                time.sleep(check_interval)
        
        if not ssh_connected:
            console.print(f"[red]✗[/] {vm_name}: SSH not ready after {max_wait_time}s")
            console.print(f"[yellow]  → Cloud-init may still be running on the VM[/]")
            console.print(f"[dim]  → Check VM console: sudo virsh console {vm_name}[/]")
            console.print(f"[dim]  → Or wait a few more minutes and try again[/]")
            console.print(f"[dim]  → You can also manually verify: ssh -i {ssh_key_path} {vm_user}@{ip}[/]")
    
    if not ssh_ready:
        console.print("\n[red]No VMs are ready for SSH connections[/]")
        console.print("[yellow]Please wait for cloud-init to complete on the VMs[/]")
        console.print("[dim]You can check VM status with: ./conductor.py status[/]")
        return
    
    console.print(f"\n[dim]Proceeding with {len(ssh_ready)} VM(s) that are SSH-ready...[/]\n")
    
    # Build SSH command
    ssh_cmd_base = [
        "ssh",
        "-i", ssh_key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=5",
        "-o", "PasswordAuthentication=no",
        "-o", "PubkeyAuthentication=yes",
        "-o", "BatchMode=yes",  # Non-interactive mode
    ]
    
    # Add verbose flag if DEBUG is set
    if os.getenv("DEBUG"):
        ssh_cmd_base.append("-v")
    else:
        ssh_cmd_base.append("-q")
    
    # Handle localhost in upload URL - VMs can't reach localhost, need host IP
    if upload_url:
        # Check if URL contains localhost or 127.0.0.1
        if "localhost" in upload_url or "127.0.0.1" in upload_url:
            # Try to find the host IP on the libvirt network
            host_ip_result = run_command(
                ["ip", "addr", "show", "virbr0"],
                capture=True,
                check=False
            )
            
            host_ip = None
            if host_ip_result.returncode == 0:
                import re
                # Extract IP from virbr0 interface (e.g., "inet 192.168.124.1/24")
                ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', host_ip_result.stdout)
                if ip_match:
                    host_ip = ip_match.group(1)
            
            if host_ip:
                # Replace localhost/127.0.0.1 with host IP
                fixed_url = upload_url.replace("localhost", host_ip).replace("127.0.0.1", host_ip)
                console.print(f"[yellow]⚠[/] Replaced localhost with host IP: {host_ip}")
                console.print(f"[dim]  Original URL: {upload_url}[/]")
                console.print(f"[dim]  Using URL: {fixed_url}[/]\n")
                upload_url = fixed_url
            else:
                console.print(f"[yellow]⚠[/] Warning: Upload URL contains 'localhost' or '127.0.0.1'")
                console.print(f"[yellow]  VMs cannot reach localhost - they need the host's IP address[/]")
                console.print(f"[yellow]  Please use the host IP instead (e.g., http://192.168.124.1:8080/api/v1/ingest)[/]")
                console.print(f"[dim]  Continuing anyway, but upload may fail...[/]\n")
    
    # Build snail-core command
    snail_cmd = "/opt/snail-core/venv/bin/snail run"
    if upload_url:
        snail_cmd = f"SNAIL_UPLOAD_URL={upload_url} {snail_cmd}"
    
    # Run on each VM (only those that are SSH-ready)
    results = {}
    for vm_name, ip in ssh_ready.items():
        console.print(f"[cyan]Running on {vm_name} ({ip})...[/]")
        
        ssh_cmd = ssh_cmd_base + [
            f"{vm_user}@{ip}",
            snail_cmd
        ]
        
        try:
            result = run_command(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=timeout
            )
            
            if result.returncode == 0:
                console.print(f"[green]✓[/] {vm_name}: Success")
                # Show output if available (snail-core may produce output)
                if result.stdout and result.stdout.strip():
                    # Show last few lines of output
                    output_lines = result.stdout.strip().split('\n')
                    if len(output_lines) > 0:
                        # Look for key messages
                        for line in output_lines[-5:]:  # Last 5 lines
                            if any(keyword in line.lower() for keyword in ['upload', 'success', 'error', 'failed', 'collecting']):
                                console.print(f"[dim]  → {line[:100]}[/]")
                results[vm_name] = ("success", result.stdout)
            else:
                console.print(f"[red]✗[/] {vm_name}: Failed (exit code {result.returncode})")
                
                # Provide helpful error messages
                error_output = result.stderr or result.stdout or ""
                if "Permission denied" in error_output or "publickey" in error_output:
                    console.print(f"[yellow]  → SSH authentication failed[/]")
                    console.print(f"[dim]  → Ensure the public key is in the VM's authorized_keys[/]")
                    console.print(f"[dim]  → Check if cloud-init has finished on the VM[/]")
                    console.print(f"[dim]  → Try: ssh -i {ssh_key_path} {vm_user}@{ip} 'echo test'[/]")
                elif "Connection refused" in error_output or "No route to host" in error_output:
                    console.print(f"[yellow]  → Cannot connect to VM[/]")
                    console.print(f"[dim]  → VM may still be booting or network not ready[/]")
                else:
                    if error_output:
                        # Show more detailed error output
                        error_lines = error_output.split('\n')
                        # Filter out SSH warnings and show actual errors
                        relevant_lines = [
                            line for line in error_lines
                            if line.strip() and not line.strip().startswith('Warning:')
                        ]
                        if not relevant_lines:
                            relevant_lines = error_lines[:5]  # Fallback to first 5 lines
                        
                        for line in relevant_lines[:5]:  # Show up to 5 relevant lines
                            if line.strip():
                                console.print(f"[dim]  → {line[:150]}[/]")
                        
                        # Also check stdout for errors
                        if result.stdout:
                            stdout_lines = result.stdout.split('\n')
                            for line in stdout_lines:
                                if any(keyword in line.lower() for keyword in ['error', 'failed', 'cannot', 'unable']):
                                    console.print(f"[dim]  → {line[:150]}[/]")
                
                results[vm_name] = ("failed", error_output)
        except subprocess.TimeoutExpired:
            console.print(f"[yellow]⚠[/] {vm_name}: Timeout after {timeout}s")
            results[vm_name] = ("timeout", None)
        except Exception as e:
            console.print(f"[red]✗[/] {vm_name}: Error - {e}")
            results[vm_name] = ("error", str(e))
    
    # Summary
    console.print()
    success_count = sum(1 for status, _ in results.values() if status == "success")
    failed_count = len(results) - success_count
    
    if success_count > 0:
        console.print(f"[green]✓ {success_count} VM(s) completed successfully[/]")
    if failed_count > 0:
        console.print(f"[red]✗ {failed_count} VM(s) failed or timed out[/]")
    
    console.print()


def destroy_vms(
    force: bool,
    vm_name: str | None
) -> None:
    """
    Destroy (shutdown and remove) VMs.
    
    Args:
        force: Skip confirmation prompt
        vm_name: Specific VM name to destroy, or None for all VMs
    """
    console.print(Panel.fit(
        "[bold red]Destroying VMs[/]",
        border_style="red"
    ))
    
    config = load_config()
    vms_config = config.get("vms", {})
    host_config = config.get("host", {})
    vm_prefix = vms_config.get("name_prefix", "conductor-test")
    image_dir = host_config.get("image_dir", "/var/lib/libvirt/images")
    cloudinit_dir = host_config.get("cloudinit_dir", "/tmp/conductor-test-cloudinit")
    
    # Handle specific VM
    if vm_name:
        # Check if VM exists
        result = run_command(
            ["virsh", "list", "--all", "--name"],
            sudo=True,
            check=False
        )
        
        if vm_name not in result.stdout:
            console.print(f"[red]VM not found: {vm_name}[/]")
            sys.exit(1)
        
        if not force:
            if not click.confirm(f"Are you sure you want to destroy {vm_name}?"):
                console.print("[yellow]Aborted[/]")
                return
        
        _destroy_single_vm(vm_name, image_dir)
        console.print(f"\n[green]✓ VM {vm_name} destroyed[/]")
        return
    
    # Get all conductor-test VMs
    vms = get_vm_list()
    
    if not vms:
        console.print(f"[yellow]No VMs found with prefix: {vm_prefix}[/]")
        return
    
    console.print(f"\n[dim]Found {len(vms)} VM(s) to destroy:[/]")
    for vm in vms:
        console.print(f"  - {vm}")
    console.print()
    
    if not force:
        if not click.confirm(f"Are you sure you want to destroy ALL {len(vms)} VM(s)?"):
            console.print("[yellow]Aborted[/]")
            return
    
    # Destroy each VM
    console.print()
    for vm in vms:
        _destroy_single_vm(vm, image_dir)
    
    # Clean up cloud-init directory
    cloudinit_path = Path(cloudinit_dir)
    if cloudinit_path.exists():
        console.print(f"\n[dim]Cleaning up cloud-init directory...[/]")
        import shutil
        
        # Check if directory is in a system path that requires root
        needs_sudo = (
            str(cloudinit_path).startswith("/var/") or
            str(cloudinit_path).startswith("/usr/") or
            str(cloudinit_path).startswith("/etc/") or
            str(cloudinit_path).startswith("/opt/")
        )
        
        try:
            if needs_sudo:
                # Use sudo to remove system directory
                result = run_command(
                    ["rm", "-rf", str(cloudinit_path)],
                    sudo=True,
                    check=False
                )
                if result.returncode == 0:
                    console.print(f"[green]✓[/] Removed {cloudinit_dir}")
                else:
                    console.print(f"[yellow]⚠[/] Failed to remove cloud-init directory: {result.stderr}")
            else:
                # Regular removal for user-writable paths
                shutil.rmtree(cloudinit_path)
                console.print(f"[green]✓[/] Removed {cloudinit_dir}")
        except Exception as e:
            console.print(f"[yellow]⚠[/] Failed to remove cloud-init directory: {e}")
            if needs_sudo:
                console.print(f"[dim]  → Try manually: sudo rm -rf {cloudinit_dir}[/]")
    
    # Remove VM list file if it exists
    vm_list_file = Path(__file__).parent.parent / "vm-list.txt"
    if vm_list_file.exists():
        try:
            vm_list_file.unlink()
            console.print(f"[green]✓[/] Removed vm-list.txt")
        except Exception as e:
            console.print(f"[yellow]⚠[/] Failed to remove vm-list.txt: {e}")
    
    console.print(f"\n[green]✓ All {len(vms)} VM(s) have been destroyed![/]")


def shutdown_vms(
    force: bool,
    vm_name: str | None
) -> None:
    """
    Shutdown (stop) VMs without deleting them.
    
    Args:
        force: Skip confirmation prompt
        vm_name: Specific VM name to shutdown, or None for all VMs
    """
    console.print(Panel.fit(
        "[bold yellow]Shutting Down VMs[/]",
        border_style="yellow"
    ))
    
    config = load_config()
    vms_config = config.get("vms", {})
    vm_prefix = vms_config.get("name_prefix", "conductor-test")
    
    # Handle specific VM
    if vm_name:
        # Check if VM exists
        result = run_command(
            ["virsh", "list", "--all", "--name"],
            sudo=True,
            check=False
        )
        
        if vm_name not in result.stdout:
            console.print(f"[red]VM not found: {vm_name}[/]")
            sys.exit(1)
        
        # Check if VM is running
        state_result = run_command(
            ["virsh", "domstate", vm_name],
            sudo=True,
            check=False
        )
        
        state = state_result.stdout.strip() if state_result.returncode == 0 else "unknown"
        
        if state != "running":
            console.print(f"[yellow]VM {vm_name} is not running (state: {state})[/]")
            return
        
        if not force:
            if not click.confirm(f"Are you sure you want to shutdown {vm_name}?"):
                console.print("[yellow]Aborted[/]")
                return
        
        _shutdown_single_vm(vm_name)
        console.print(f"\n[green]✓ VM {vm_name} shutdown[/]")
        return
    
    # Get all running VMs
    running_vms = get_running_vms()
    
    if not running_vms:
        console.print(f"[yellow]No running VMs found with prefix: {vm_prefix}[/]")
        return
    
    console.print(f"\n[dim]Found {len(running_vms)} running VM(s) to shutdown:[/]")
    for vm in running_vms:
        console.print(f"  - {vm}")
    console.print()
    
    if not force:
        if not click.confirm(f"Are you sure you want to shutdown ALL {len(running_vms)} VM(s)?"):
            console.print("[yellow]Aborted[/]")
            return
    
    # Shutdown each VM
    console.print()
    for vm in running_vms:
        _shutdown_single_vm(vm)
    
    console.print(f"\n[green]✓ All {len(running_vms)} VM(s) have been shutdown![/]")


def _shutdown_single_vm(vm_name: str) -> None:
    """
    Shutdown a single VM gracefully.
    
    Args:
        vm_name: Name of the VM to shutdown
    """
    console.print(f"[cyan]Shutting down {vm_name}...[/]")
    
    # Try graceful shutdown first
    console.print(f"  [dim]Sending shutdown signal...[/]")
    result = run_command(
        ["virsh", "shutdown", vm_name],
        sudo=True,
        check=False
    )
    
    if result.returncode == 0:
        # Wait a bit for graceful shutdown
        import time
        time.sleep(2)
        
        # Check if still running
        state_result = run_command(
            ["virsh", "domstate", vm_name],
            sudo=True,
            check=False
        )
        
        state = state_result.stdout.strip() if state_result.returncode == 0 else "unknown"
        
        if state == "running":
            console.print(f"  [dim]VM still running, forcing shutdown...[/]")
            run_command(
                ["virsh", "destroy", vm_name],
                sudo=True,
                check=False
            )
            console.print(f"  [green]✓[/] {vm_name} forced shutdown")
        else:
            console.print(f"  [green]✓[/] {vm_name} shutdown gracefully")
    else:
        # If shutdown fails, try destroy as fallback
        console.print(f"  [dim]Shutdown command failed, forcing...[/]")
        run_command(
            ["virsh", "destroy", vm_name],
            sudo=True,
            check=False
        )
        console.print(f"  [green]✓[/] {vm_name} forced shutdown")


def start_vms(
    force: bool,
    vm_name: str | None
) -> None:
    """
    Start stopped VMs.
    
    Args:
        force: Skip confirmation prompt
        vm_name: Specific VM name to start, or None for all stopped VMs
    """
    console.print(Panel.fit(
        "[bold green]Starting VMs[/]",
        border_style="green"
    ))
    
    config = load_config()
    vms_config = config.get("vms", {})
    vm_prefix = vms_config.get("name_prefix", "conductor-test")
    
    # Handle specific VM
    if vm_name:
        # Check if VM exists
        result = run_command(
            ["virsh", "list", "--all", "--name"],
            sudo=True,
            check=False
        )
        
        if vm_name not in result.stdout:
            console.print(f"[red]VM not found: {vm_name}[/]")
            sys.exit(1)
        
        # Check if VM is already running
        state_result = run_command(
            ["virsh", "domstate", vm_name],
            sudo=True,
            check=False
        )
        
        state = state_result.stdout.strip() if state_result.returncode == 0 else "unknown"
        
        if state == "running":
            console.print(f"[yellow]VM {vm_name} is already running[/]")
            return
        
        if not force:
            if not click.confirm(f"Are you sure you want to start {vm_name}?"):
                console.print("[yellow]Aborted[/]")
                return
        
        _start_single_vm(vm_name)
        console.print(f"\n[green]✓ VM {vm_name} started[/]")
        return
    
    # Get all stopped VMs
    stopped_vms = get_stopped_vms()
    
    if not stopped_vms:
        console.print(f"[yellow]No stopped VMs found with prefix: {vm_prefix}[/]")
        return
    
    console.print(f"\n[dim]Found {len(stopped_vms)} stopped VM(s) to start:[/]")
    for vm in stopped_vms:
        console.print(f"  - {vm}")
    console.print()
    
    if not force:
        if not click.confirm(f"Are you sure you want to start ALL {len(stopped_vms)} VM(s)?"):
            console.print("[yellow]Aborted[/]")
            return
    
    # Start each VM
    console.print()
    for vm in stopped_vms:
        _start_single_vm(vm)
    
    console.print(f"\n[green]✓ All {len(stopped_vms)} VM(s) have been started![/]")


def _ensure_cloudinit_iso_or_detach(vm_name: str) -> None:
    """
    Ensure cloud-init ISO exists or detach it from VM definition.
    
    Cloud-init ISO is only needed for first boot. If it's missing,
    we try to recreate it. If that fails, we detach it from the VM
    definition since it's no longer needed.
    
    Args:
        vm_name: Name of the VM to check
    """
    config = load_config()
    host_config = config.get("host", {})
    cloudinit_dir = host_config.get("cloudinit_dir", "/tmp/conductor-test-cloudinit")
    cloudinit_path = Path(cloudinit_dir) / vm_name / "cloud-init.iso"
    
    # Check if ISO exists
    if cloudinit_path.exists():
        return  # ISO exists, nothing to do
    
    # ISO is missing - check if we can recreate it
    cloudinit_dir_path = Path(cloudinit_dir) / vm_name
    user_data_path = cloudinit_dir_path / "user-data"
    meta_data_path = cloudinit_dir_path / "meta-data"
    
    if user_data_path.exists() and meta_data_path.exists():
        # We can recreate the ISO
        console.print(f"  [yellow]⚠[/] Cloud-init ISO missing, recreating...")
        try:
            # Use genisoimage to recreate the ISO
            run_command(
                [
                    "genisoimage",
                    "-output", str(cloudinit_path),
                    "-volid", "cidata",
                    "-joliet",
                    "-rock",
                    str(user_data_path),
                    str(meta_data_path),
                ],
                sudo=True,
                check=True,
            )
            console.print(f"  [green]✓[/] Cloud-init ISO recreated")
            return
        except subprocess.CalledProcessError:
            console.print(f"  [red]✗[/] Failed to recreate cloud-init ISO")
            # Fall through to detach
    
    # Can't recreate - detach the ISO from VM definition
    # Cloud-init ISO is only needed for first boot anyway
    console.print(f"  [yellow]⚠[/] Cloud-init ISO missing and cannot be recreated")
    console.print(f"  [dim]  → Detaching cloud-init ISO from VM (only needed for first boot)[/]")
    
    # Get list of block devices to find the cloud-init ISO
    result = run_command(
        ["virsh", "domblklist", vm_name, "--details"],
        sudo=True,
        check=False,
    )
    
    if result.returncode != 0:
        console.print(f"  [yellow]⚠[/] Could not list VM block devices")
        return
    
    # Look for cloud-init ISO in the block device list
    # Format: "Target     Source" or "hdb        /path/to/cloud-init.iso"
    import re
    for line in result.stdout.split('\n'):
        if 'cloud-init.iso' in line:
            # Extract device name (first column)
            parts = line.split()
            if len(parts) >= 2:
                device = parts[0]
                # Detach the disk
                detach_result = run_command(
                    ["virsh", "detach-disk", vm_name, device, "--config"],
                    sudo=True,
                    check=False,
                )
                
                if detach_result.returncode == 0:
                    console.print(f"  [green]✓[/] Detached cloud-init ISO from VM")
                    return
                else:
                    console.print(f"  [yellow]⚠[/] Could not detach device {device}")
    
    # If we get here, cloud-init ISO wasn't found in block list
    # It might already be detached or the VM definition is inconsistent
    console.print(f"  [dim]  → Cloud-init ISO not found in VM block devices (may already be detached)[/]")


def check_cloudinit_status(
    vm_name: str | None
) -> None:
    """
    Check cloud-init status and logs for a VM.
    
    Shows detailed information about cloud-init progress, including:
    - Current status (running, done, error)
    - Recent log entries
    - What cloud-init is currently doing
    
    Args:
        vm_name: Specific VM name to check, or None to check all running VMs
    """
    console.print(Panel.fit(
        "[bold cyan]Cloud-Init Status Check[/]",
        border_style="cyan"
    ))
    
    config = load_config()
    vms_config = config.get("vms", {})
    host_config = config.get("host", {})
    vm_prefix = vms_config.get("name_prefix", "conductor-test")
    ssh_key_path = host_config.get("ssh_key_path", f"{os.path.expanduser('~')}/.ssh/conductor-test-key")
    vm_user = vms_config.get("user", "conductor")
    
    # Handle specific VM
    if vm_name:
        _check_single_vm_cloudinit(vm_name, ssh_key_path, vm_user)
        return
    
    # Check all running VMs
    running_vms = get_running_vms()
    
    if not running_vms:
        console.print(f"[yellow]No running VMs found with prefix: {vm_prefix}[/]")
        return
    
    console.print(f"\n[dim]Found {len(running_vms)} running VM(s)...[/]\n")
    
    for vm in running_vms:
        _check_single_vm_cloudinit(vm, ssh_key_path, vm_user)
        console.print()  # Add spacing between VMs


def _check_single_vm_cloudinit(vm_name: str, ssh_key_path: str, vm_user: str) -> None:
    """
    Check cloud-init status for a single VM.
    
    Args:
        vm_name: Name of the VM
        ssh_key_path: Path to SSH private key
        vm_user: Username for SSH
    """
    console.print(f"[bold]{vm_name}[/]")
    
    # Get VM state and uptime info
    vm_state = get_vm_state(vm_name)
    if vm_state != "running":
        console.print(f"  [yellow]⚠[/] VM is not running (state: {vm_state})")
        return
    
    # Get VM IP
    ip = get_vm_ip(vm_name)
    if not ip:
        console.print(f"  [yellow]⚠[/] No IP address yet (VM is booting)")
        console.print(f"  [dim]  → This is normal during early boot phase[/]")
        console.print(f"  [dim]  → Cloud-init typically takes 1-3 minutes to complete[/]")
        console.print(f"  [dim]  → Check VM console: sudo virsh console {vm_name}[/]")
        console.print(f"  [dim]  → Or wait a bit and try: ./conductor.py cloudinit-status --vm {vm_name}[/]")
        return
    
    console.print(f"  [dim]IP: {ip}[/]")
    
    # Try to ping the VM first (quick connectivity check)
    ping_result = run_command(
        ["ping", "-c", "1", "-W", "2", ip],
        capture=True,
        check=False,
        timeout=5
    )
    
    if ping_result.returncode != 0:
        console.print(f"  [yellow]⚠[/] VM not responding to ping")
        console.print(f"  [dim]  → VM may still be booting or network not ready[/]")
        console.print(f"  [dim]  → Check VM console: sudo virsh console {vm_name}[/]")
        return
    
    # Try to get cloud-init status via SSH
    status_cmd = [
        "ssh",
        "-i", ssh_key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-q",
        f"{vm_user}@{ip}",
        "cloud-init status 2>/dev/null || echo 'cloud-init-command-not-found'"
    ]
    
    result = run_command(status_cmd, capture=True, check=False, timeout=10)
    
    if result.returncode != 0:
        # SSH failed - provide detailed troubleshooting
        console.print(f"  [yellow]⚠[/] Cannot connect via SSH")
        console.print(f"  [dim]  → Cloud-init is likely still running (SSH keys not installed yet)[/]")
        console.print()
        
        # Check if console is available
        console_check = run_command(
            ["virsh", "qemu-monitor-command", vm_name, "--hmp", "info status"],
            sudo=True,
            check=False,
            timeout=3
        )
        
        console.print(f"  [bold]Troubleshooting steps:[/]")
        console.print()
        console.print(f"  [dim]  1. Check VM console:[/] [cyan]sudo virsh console {vm_name} --force[/]")
        console.print(f"  [dim]     [yellow]Important:[/] The 'conductor' user is created by cloud-init.[/]")
        console.print(f"  [dim]     [yellow]If cloud-init hasn't finished, you may need to login as 'root' first.[/]")
        console.print(f"  [dim]     [yellow]Try root password:[/] [cyan]conductortest123[/] (same as conductor user)[/]")
        console.print(f"  [dim]     [yellow]Or wait for cloud-init to complete, then login as:[/] [cyan]conductor[/]")
        console.print(f"  [dim]     [yellow]Password:[/] [cyan]conductortest123[/]")
        console.print(f"  [dim]     [yellow]Once logged in, check:[/] [cyan]cloud-init status[/]")
        console.print(f"  [dim]     [yellow]Or check if user exists:[/] [cyan]id conductor[/]")
        console.print()
        console.print(f"  [dim]  2. Wait and retry:[/] [cyan]./conductor.py cloudinit-status --vm {vm_name}[/]")
        console.print(f"  [dim]     (Cloud-init typically takes 1-3 minutes)[/]")
        console.print()
        console.print(f"  [dim]  3. Check VM boot time:[/] [cyan]sudo virsh dominfo {vm_name} | grep 'CPU time'[/]")
        console.print(f"  [dim]     (If CPU time is very low, VM just started)[/]")
        console.print()
        console.print(f"  [dim]  4. Try alternative access:[/]")
        console.print(f"  [dim]     [yellow]  • Check if qemu-guest-agent is available:[/]")
        agent_cmd = f"sudo virsh qemu-agent-command {vm_name} '{{\"execute\":\"guest-info\"}}'"
        console.print(f"  [dim]     [yellow]    {agent_cmd}[/]")
        return
    
    if "cloud-init-command-not-found" in result.stdout:
        # Try alternative: check boot-finished file
        check_cmd = [
            "ssh",
            "-i", ssh_key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
            "-q",
            f"{vm_user}@{ip}",
            "if [ -f /var/lib/cloud/instance/boot-finished ]; then echo 'done'; else echo 'running'; fi"
        ]
        
        check_result = run_command(check_cmd, capture=True, check=False, timeout=10)
        if check_result.returncode == 0:
            if "done" in check_result.stdout:
                console.print(f"  [green]✓[/] Cloud-init: [green]Complete[/]")
            else:
                console.print(f"  [yellow]⏳[/] Cloud-init: [yellow]Still running[/]")
                console.print(f"  [dim]  → Boot-finished file not found yet[/]")
        return
    
    # Parse cloud-init status output
    status_output = result.stdout.strip()
    
    if "status: done" in status_output or "status: active" in status_output:
        console.print(f"  [green]✓[/] Cloud-init: [green]Complete[/]")
    elif "status: running" in status_output:
        console.print(f"  [yellow]⏳[/] Cloud-init: [yellow]Running[/]")
        
        # Try to get what cloud-init is doing
        stage_cmd = [
            "ssh",
            "-i", ssh_key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
            "-q",
            f"{vm_user}@{ip}",
            "cat /var/lib/cloud/data/status.json 2>/dev/null | grep -o '\"stage\":\"[^\"]*\"' | head -1 || echo ''"
        ]
        
        stage_result = run_command(stage_cmd, capture=True, check=False, timeout=10)
        if stage_result.returncode == 0 and stage_result.stdout.strip():
            stage = stage_result.stdout.strip().replace('"stage":"', '').replace('"', '')
            if stage:
                console.print(f"  [dim]  → Current stage: {stage}[/]")
    elif "status: error" in status_output:
        console.print(f"  [red]✗[/] Cloud-init: [red]Error[/]")
        console.print(f"  [dim]  → Check logs: ./conductor.py cloudinit-logs {vm_name}[/]")
    else:
        console.print(f"  [yellow]?[/] Cloud-init: [yellow]Unknown status[/]")
        console.print(f"  [dim]  → Output: {status_output[:100]}[/]")
    
    # Show recent log entries
    console.print(f"  [dim]Recent cloud-init activity:[/]")
    log_cmd = [
        "ssh",
        "-i", ssh_key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-q",
        f"{vm_user}@{ip}",
        "tail -20 /var/log/cloud-init.log 2>/dev/null | tail -5 || echo 'Log file not accessible'"
    ]
    
    log_result = run_command(log_cmd, capture=True, check=False, timeout=10)
    if log_result.returncode == 0 and log_result.stdout.strip():
        log_lines = log_result.stdout.strip().split('\n')
        for line in log_lines[-3:]:  # Show last 3 lines
            if line.strip() and "Log file not accessible" not in line:
                # Truncate long lines
                display_line = line[:120] + "..." if len(line) > 120 else line
                console.print(f"  [dim]    {display_line}[/]")


def wait_for_ssh(
    vm_name: str,
    timeout: int = 300,
    interval: int = 5
) -> None:
    """
    Wait for SSH to become available on a VM.
    
    Polls SSH connectivity and shows progress while waiting for cloud-init
    to complete and SSH keys to be added.
    
    Args:
        vm_name: Name of the VM to wait for
        timeout: Maximum time to wait in seconds (default: 300 = 5 minutes)
        interval: How often to check in seconds (default: 5)
    """
    console.print(Panel.fit(
        f"[bold cyan]Waiting for SSH: {vm_name}[/]",
        border_style="cyan"
    ))
    
    config = load_config()
    host_config = config.get("host", {})
    vms_config = config.get("vms", {})
    ssh_key_path = host_config.get("ssh_key_path", f"{os.path.expanduser('~')}/.ssh/conductor-test-key")
    vm_user = vms_config.get("user", "conductor")
    
    # Get VM IP
    ip = get_vm_ip(vm_name)
    if not ip:
        console.print(f"[red]✗[/] No IP address (VM may still be booting)")
        console.print(f"[dim]Check VM status: ./conductor.py status[/]")
        return
    
    console.print(f"[dim]VM IP: {ip}[/]")
    console.print(f"[dim]Waiting up to {timeout} seconds for SSH to become available...[/]\n")
    
    import time
    import socket
    start_time = time.time()
    last_status = None
    
    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)
        
        # Check if SSH port is open
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        port_open = sock.connect_ex((ip, 22)) == 0
        sock.close()
        
        if not port_open:
            status = "SSH port not open"
            if status != last_status:
                console.print(f"[yellow]⏳[/] [{elapsed}s] {status}...")
                last_status = status
            time.sleep(interval)
            continue
        
        # Port is open, try SSH connection
        ssh_test_cmd = [
            "ssh",
            "-i", ssh_key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=2",
            "-o", "BatchMode=yes",
            "-q",
            f"{vm_user}@{ip}",
            "echo 'SSH_OK'"
        ]
        
        result = run_command(ssh_test_cmd, capture=True, check=False, timeout=3)
        
        if result.returncode == 0 and "SSH_OK" in result.stdout:
            console.print(f"\n[green]✓[/] SSH is now available! (took {elapsed}s)")
            console.print(f"[dim]You can now connect with:[/]")
            console.print(f"[cyan]  ssh -i {ssh_key_path} {vm_user}@{ip}[/]")
            return
        else:
            status = "SSH port open, waiting for keys"
            if status != last_status:
                console.print(f"[yellow]⏳[/] [{elapsed}s] {status}...")
                last_status = status
        
        time.sleep(interval)
    
    # Timeout
    console.print(f"\n[red]✗[/] Timeout after {timeout} seconds")
    console.print(f"[yellow]SSH is still not available[/]")
    console.print(f"[dim]Possible issues:[/]")
    console.print(f"[dim]  → Cloud-init may have failed[/]")
    console.print(f"[dim]  → Check VM console: sudo virsh console {vm_name} --force[/]")
    console.print(f"[dim]  → Check cloud-init logs: ./conductor.py debug {vm_name}[/]")


def debug_vm(
    vm_name: str
) -> None:
    """
    Debug a VM using multiple methods without requiring login.
    
    Tries various approaches to inspect VM state, cloud-init status,
    and configuration without needing console or SSH access.
    
    Args:
        vm_name: Name of the VM to debug
    """
    console.print(Panel.fit(
        f"[bold yellow]VM Debug: {vm_name}[/]",
        border_style="yellow"
    ))
    
    config = load_config()
    host_config = config.get("host", {})
    vms_config = config.get("vms", {})
    cloudinit_dir = host_config.get("cloudinit_dir", "/tmp/conductor-test-cloudinit")
    ssh_key_path = host_config.get("ssh_key_path", f"{os.path.expanduser('~')}/.ssh/conductor-test-key")
    vm_user = vms_config.get("user", "conductor")
    
    console.print(f"\n[bold]1. VM Basic Information[/]\n")
    
    # Check VM state
    vm_state = get_vm_state(vm_name)
    console.print(f"  [dim]State:[/] {vm_state}")
    
    # Get VM info
    info_result = run_command(
        ["virsh", "dominfo", vm_name],
        sudo=True,
        check=False
    )
    if info_result.returncode == 0:
        for line in info_result.stdout.strip().split('\n'):
            if 'CPU time' in line or 'Max memory' in line or 'Used memory' in line:
                console.print(f"  [dim]{line.strip()}[/]")
    
    # Note: CPU time is cumulative CPU usage, not wall-clock uptime
    # Check if VM was recently started by looking at creation/start time
    console.print(f"  [dim]Note: 'CPU time' is cumulative CPU usage, not actual uptime[/]")
    
    # Try to get actual boot time from VM
    # Check when VM was last started using virsh
    start_time_result = run_command(
        ["virsh", "dominfo", vm_name],
        sudo=True,
        check=False
    )
    
    # Try to read /proc/uptime or similar via guest-file-read
    import json
    import base64
    try:
        uptime_read_cmd = '{"execute":"guest-file-read","arguments":{"path":"/proc/uptime","count":20}}'
        uptime_result = run_command(
            ["virsh", "qemu-agent-command", vm_name, uptime_read_cmd],
            sudo=True,
            check=False,
            timeout=5
        )
        if uptime_result.returncode == 0:
            result_data = json.loads(uptime_result.stdout)
            if "return" in result_data and "content" in result_data["return"]:
                uptime_content = base64.b64decode(result_data["return"]["content"]).decode('utf-8')
                if uptime_content.strip():
                    uptime_seconds = float(uptime_content.strip().split()[0])
                    uptime_minutes = int(uptime_seconds / 60)
                    uptime_hours = int(uptime_minutes / 60)
                    if uptime_hours > 0:
                        console.print(f"  [cyan]Actual VM uptime: ~{uptime_hours}h {uptime_minutes % 60}m[/]")
                    elif uptime_minutes > 0:
                        console.print(f"  [cyan]Actual VM uptime: ~{uptime_minutes}m {int(uptime_seconds % 60)}s[/]")
                    else:
                        console.print(f"  [cyan]Actual VM uptime: ~{int(uptime_seconds)}s[/]")
                    
                    # If uptime is very short but VM was created long ago, it was restarted
                    if uptime_seconds < 120:  # Less than 2 minutes
                        console.print(f"  [yellow]⚠[/] VM appears to have been restarted recently")
                        console.print(f"  [dim]  → If you created this VM 10+ minutes ago, it was likely stopped/restarted[/]")
                        console.print(f"  [dim]  → This explains why cloud-init is still running[/]")
            elif "return" in result_data and "errno" in result_data["return"]:
                console.print(f"  [dim]  Cannot read /proc/uptime (guest-file-read not available or file not accessible)[/]")
        else:
            console.print(f"  [dim]  Cannot read /proc/uptime (guest agent may not support guest-file-read)[/]")
    except Exception as e:
        console.print(f"  [dim]  Error reading uptime: {e}[/]")
    
    # Get IP
    ip = get_vm_ip(vm_name)
    if ip:
        console.print(f"  [dim]IP Address:[/] {ip}")
        
        # Test connectivity
        ping_result = run_command(
            ["ping", "-c", "1", "-W", "2", ip],
            capture=True,
            check=False,
            timeout=5
        )
        if ping_result.returncode == 0:
            console.print(f"  [green]✓[/] VM is reachable via ping")
        else:
            console.print(f"  [red]✗[/] VM not responding to ping")
    else:
        console.print(f"  [yellow]⚠[/] No IP address assigned yet")
    
    console.print(f"\n[bold]2. Cloud-Init Configuration[/]\n")
    
    # Check cloud-init user-data
    cloudinit_user_data = Path(cloudinit_dir) / vm_name / "user-data"
    if cloudinit_user_data.exists():
        console.print(f"  [green]✓[/] Cloud-init user-data exists: {cloudinit_user_data}")
        
        # Show relevant parts and validate
        try:
            with open(cloudinit_user_data) as f:
                content = f.read()
            
            # Validate YAML syntax
            try:
                yaml.safe_load(content)
                console.print(f"  [green]✓[/] Cloud-init user-data is valid YAML")
            except yaml.YAMLError as e:
                console.print(f"  [red]✗[/] Cloud-init user-data has YAML syntax errors!")
                console.print(f"  [red]  Error: {e}[/]")
                console.print(f"  [yellow]  → This will prevent cloud-init from working![/]")
            
            # Check for SSH key configuration (critical for SSH access)
            if 'ssh_authorized_keys:' in content:
                console.print(f"  [green]✓[/] SSH authorized keys configuration found")
                # Count how many keys
                key_count = content.count('- ssh-')
                if key_count > 0:
                    console.print(f"  [dim]  Found {key_count} SSH key(s) in config[/]")
                else:
                    console.print(f"  [yellow]⚠[/] SSH keys section exists but no keys found![/]")
            else:
                console.print(f"  [red]✗[/] SSH authorized keys not found in user-data!")
                console.print(f"  [yellow]  → This explains why SSH authentication fails![/]")
            
            # Check for root password config
            if 'root:' in content and 'chpasswd' in content:
                console.print(f"  [green]✓[/] Root password configuration found in chpasswd")
            else:
                console.print(f"  [yellow]⚠[/] Root password not found in chpasswd")
            
            if 'disable_root: false' in content:
                console.print(f"  [green]✓[/] Root login is enabled (disable_root: false)")
            elif 'disable_root: true' in content:
                console.print(f"  [red]✗[/] Root login is disabled (disable_root: true)")
            else:
                console.print(f"  [yellow]⚠[/] disable_root setting not found (defaults to true)")
            
            # Check for root in users section
            if 'name: root' in content or '- name: root' in content:
                console.print(f"  [green]✓[/] Root user defined in users section")
            else:
                console.print(f"  [yellow]⚠[/] Root user not in users section")
        except Exception as e:
            console.print(f"  [red]✗[/] Error reading user-data: {e}")
    else:
        console.print(f"  [red]✗[/] Cloud-init user-data not found: {cloudinit_user_data}")
    
    # Check cloud-init ISO
    cloudinit_iso = Path(cloudinit_dir) / vm_name / "cloud-init.iso"
    if cloudinit_iso.exists():
        console.print(f"  [green]✓[/] Cloud-init ISO exists: {cloudinit_iso}")
        iso_size = cloudinit_iso.stat().st_size
        console.print(f"  [dim]  ISO size: {iso_size} bytes[/]")
    else:
        console.print(f"  [yellow]⚠[/] Cloud-init ISO not found")
    
    console.print(f"\n[bold]3. VM Disk and Storage[/]\n")
    
    # Check VM disk
    disk_result = run_command(
        ["virsh", "domblklist", vm_name, "--details"],
        sudo=True,
        check=False
    )
    if disk_result.returncode == 0:
        for line in disk_result.stdout.strip().split('\n'):
            if 'cloud-init.iso' in line or '.qcow2' in line:
                console.print(f"  [dim]{line.strip()}[/]")
    
    console.print(f"\n[bold]4. QEMU Guest Agent[/]\n")
    
    # Try qemu-guest-agent
    agent_result = run_command(
        ["virsh", "qemu-agent-command", vm_name, '{"execute":"guest-info"}'],
        sudo=True,
        check=False,
        timeout=5
    )
    if agent_result.returncode == 0:
        console.print(f"  [green]✓[/] QEMU Guest Agent is available")
        console.print(f"  [dim]  Can execute commands in VM without SSH[/]")
        
        # QEMU Guest Agent doesn't support guest-exec, use alternative methods
        console.print(f"\n  [bold]Checking VM status (using alternative methods)...[/]")
        
        import json
        import base64
        import socket
        
        # Check SSH port from host side
        console.print(f"\n  [bold]Checking SSH connectivity...[/]")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        ssh_open = sock.connect_ex((ip, 22))
        sock.close()
        
        if ssh_open == 0:
            console.print(f"  [green]✓[/] SSH port 22 is open and accepting connections")
            
            # Try SSH connection test
            ssh_test_cmd = [
                "ssh",
                "-i", ssh_key_path,
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=3",
                "-o", "BatchMode=yes",
                "-q",
                f"{vm_user}@{ip}",
                "echo 'SSH_OK'"
            ]
            ssh_test = run_command(ssh_test_cmd, capture=True, check=False, timeout=5)
            if ssh_test.returncode == 0 and "SSH_OK" in ssh_test.stdout:
                console.print(f"  [green]✓[/] SSH connection successful! Cloud-init is complete.")
            elif ssh_test.returncode == 255:
                console.print(f"  [yellow]⚠[/] SSH port open but authentication failed")
                console.print(f"  [dim]  → This usually means cloud-init hasn't added SSH keys yet[/]")
                console.print(f"  [dim]  → Wait a bit longer for cloud-init to complete[/]")
            else:
                console.print(f"  [yellow]⚠[/] SSH port open but connection failed")
        else:
            console.print(f"  [yellow]⚠[/] SSH port 22 is not open or not accepting connections")
            console.print(f"  [dim]  → SSH service may not be started yet[/]")
            console.print(f"  [dim]  → Or firewall is blocking SSH[/]")
        
        # Try to read cloud-init log file using guest-file-read (if available)
        console.print(f"\n  [bold]Trying to read cloud-init log via Guest Agent...[/]")
        
        log_read_cmd = '{"execute":"guest-file-read","arguments":{"path":"/var/log/cloud-init.log","count":50}}'
        log_result = run_command(
            ["virsh", "qemu-agent-command", vm_name, log_read_cmd],
            sudo=True,
            check=False,
            timeout=5
        )
        
        if log_result.returncode == 0:
            try:
                result_data = json.loads(log_result.stdout)
                if "return" in result_data and "content" in result_data["return"]:
                    log_content = base64.b64decode(result_data["return"]["content"]).decode('utf-8')
                    # Show last few lines
                    log_lines = log_content.strip().split('\n')
                    console.print(f"  [dim]Last few cloud-init log lines:[/]")
                    for line in log_lines[-5:]:
                        if line.strip():
                            # Color code errors/warnings
                            if any(keyword in line.lower() for keyword in ['error', 'failed', 'failure']):
                                console.print(f"  [red]  {line[:100]}[/]")
                            elif any(keyword in line.lower() for keyword in ['warning', 'warn']):
                                console.print(f"  [yellow]  {line[:100]}[/]")
                            else:
                                console.print(f"  [dim]  {line[:100]}[/]")
            except Exception as e:
                console.print(f"  [dim]  Could not parse log: {e}[/]")
        else:
            console.print(f"  [dim]  Guest file read not available or log not accessible yet[/]")
        
        # Check boot-finished file
        boot_read_cmd = '{"execute":"guest-file-read","arguments":{"path":"/var/lib/cloud/instance/boot-finished","count":10}}'
        boot_result = run_command(
            ["virsh", "qemu-agent-command", vm_name, boot_read_cmd],
            sudo=True,
            check=False,
            timeout=5
        )
        
        if boot_result.returncode == 0:
            try:
                result_data = json.loads(boot_result.stdout)
                if "return" in result_data and "content" in result_data["return"]:
                    console.print(f"  [green]✓[/] Boot-finished file exists (cloud-init complete)")
                elif "return" in result_data and "errno" in result_data["return"]:
                    console.print(f"  [yellow]⚠[/] Boot-finished file not found (cloud-init still running)")
            except Exception:
                pass
        
        # Check if boot-finished file exists
        boot_check_cmd = '{"execute":"guest-exec","arguments":{"path":"/usr/bin/test","arg":["-f","/var/lib/cloud/instance/boot-finished"],"capture-output":true}}'
        boot_result = run_command(
            ["virsh", "qemu-agent-command", vm_name, boot_check_cmd],
            sudo=True,
            check=False,
            timeout=10
        )
        
        # Check SSH service status
        console.print(f"\n  [bold]Checking SSH service via Guest Agent...[/]")
        ssh_check_cmd = '{"execute":"guest-exec","arguments":{"path":"/usr/bin/systemctl","arg":["is-active","sshd"],"capture-output":true}}'
        ssh_result = run_command(
            ["virsh", "qemu-agent-command", vm_name, ssh_check_cmd],
            sudo=True,
            check=False,
            timeout=10
        )
        
        if ssh_result.returncode == 0:
            try:
                result_data = json.loads(ssh_result.stdout)
                if "return" in result_data and "pid" in result_data["return"]:
                    pid = result_data["return"]["pid"]
                    import time
                    time.sleep(1)
                    get_result_cmd = f'{{"execute":"guest-exec-status","arguments":{{"pid":{pid}}}}}'
                    get_result = run_command(
                        ["virsh", "qemu-agent-command", vm_name, get_result_cmd],
                        sudo=True,
                        check=False,
                        timeout=5
                    )
                    if get_result.returncode == 0:
                        result_json = json.loads(get_result.stdout)
                        if "return" in result_json:
                            if "out-data" in result_json["return"]:
                                import base64
                                output = base64.b64decode(result_json["return"]["out-data"]).decode('utf-8')
                                if "active" in output.lower():
                                    console.print(f"  [green]✓[/] SSH service is active")
                                else:
                                    console.print(f"  [yellow]⚠[/] SSH service status: {output.strip()}")
                            elif "exited" in result_json["return"] and result_json["return"].get("exited") == True:
                                exitcode = result_json["return"].get("exitcode", -1)
                                if exitcode == 0:
                                    console.print(f"  [green]✓[/] SSH service check completed")
                                else:
                                    console.print(f"  [yellow]⚠[/] SSH service check failed (exit code: {exitcode})")
            except Exception as e:
                console.print(f"  [dim]  Could not parse SSH status: {e}[/]")
        
        # Check if conductor user exists
        user_check_cmd = '{"execute":"guest-exec","arguments":{"path":"/usr/bin/id","arg":["conductor"],"capture-output":true}}'
        user_result = run_command(
            ["virsh", "qemu-agent-command", vm_name, user_check_cmd],
            sudo=True,
            check=False,
            timeout=10
        )
        
        if user_result.returncode == 0:
            try:
                result_data = json.loads(user_result.stdout)
                if "return" in result_data and "pid" in result_data["return"]:
                    pid = result_data["return"]["pid"]
                    import time
                    time.sleep(1)
                    get_result_cmd = f'{{"execute":"guest-exec-status","arguments":{{"pid":{pid}}}}}'
                    get_result = run_command(
                        ["virsh", "qemu-agent-command", vm_name, get_result_cmd],
                        sudo=True,
                        check=False,
                        timeout=5
                    )
                    if get_result.returncode == 0:
                        result_json = json.loads(get_result.stdout)
                        if "return" in result_json and "out-data" in result_json["return"]:
                            import base64
                            output = base64.b64decode(result_json["return"]["out-data"]).decode('utf-8')
                            console.print(f"\n  [bold]Checking conductor user...[/]")
                            console.print(f"  [green]✓[/] Conductor user exists: {output.strip()}")
                        elif "return" in result_json and result_json["return"].get("exited") == True:
                            exitcode = result_json["return"].get("exitcode", -1)
                            if exitcode != 0:
                                console.print(f"\n  [bold]Checking conductor user...[/]")
                                console.print(f"  [yellow]⚠[/] Conductor user may not exist yet (exit code: {exitcode})")
            except Exception as e:
                pass
    else:
        console.print(f"  [yellow]⚠[/] QEMU Guest Agent not available or not responding")
        console.print(f"  [dim]  Error: {agent_result.stderr[:100] if agent_result.stderr else 'No response'}[/]")
    
    console.print(f"\n[bold]5. Boot Messages[/]\n")
    
    # Try to get recent boot messages
    console_result = run_command(
        ["virsh", "qemu-monitor-command", vm_name, "--hmp", "info status"],
        sudo=True,
        check=False,
        timeout=3
    )
    if console_result.returncode == 0:
        console.print(f"  [green]✓[/] QEMU monitor accessible")
    
    console.print(f"\n[bold]6. Recommendations[/]\n")
    
    if not ip:
        console.print(f"  [yellow]→[/] VM doesn't have an IP yet. Wait for network initialization.")
    elif ping_result.returncode != 0 if ip else True:
        console.print(f"  [yellow]→[/] VM is not responding to ping. May still be booting.")
    else:
        console.print(f"  [yellow]→[/] VM is reachable. Try SSH once cloud-init completes:")
        ssh_key_path = host_config.get("ssh_key_path", f"{os.path.expanduser('~')}/.ssh/conductor-test-key")
        vm_user = vms_config.get("user", "conductor")
        console.print(f"  [cyan]    ssh -i {ssh_key_path} {vm_user}@{ip}[/]")
    
    if not cloudinit_user_data.exists():
        console.print(f"  [red]→[/] Cloud-init user-data missing! VM may not have been created properly.")
    
    console.print(f"\n  [yellow]→[/] To view cloud-init logs (once SSH works):")
    console.print(f"  [cyan]    ./conductor.py cloudinit-logs {vm_name}[/]")
    
    console.print(f"\n  [yellow]→[/] To check cloud-init status (once SSH works):")
    console.print(f"  [cyan]    ./conductor.py cloudinit-status --vm {vm_name}[/]")
    
    # If SSH has been failing for a while, provide urgent troubleshooting
    console.print(f"\n  [bold red]⚠ URGENT: If SSH still doesn't work after 10+ minutes:[/]")
    console.print(f"  [dim]  1. Cloud-init may be stuck or failed[/]")
    console.print(f"  [dim]  2. Try to see boot messages (even without login):[/]")
    console.print(f"  [cyan]     sudo virsh console {vm_name} --force[/]")
    console.print(f"  [dim]     (Press Enter a few times, look for cloud-init errors)[/]")
    console.print(f"  [dim]  3. Check if cloud-init ISO is readable:[/]")
    console.print(f"  [cyan]     file {cloudinit_iso}[/]")
    console.print(f"  [dim]  4. Verify cloud-init user-data is valid YAML:[/]")
    console.print(f"  [cyan]     python3 -c \"import yaml; yaml.safe_load(open('{cloudinit_user_data}'))\"[/]")
    console.print(f"  [dim]  5. Consider recreating the VM:[/]")
    console.print(f"  [cyan]     ./conductor.py destroy --vm {vm_name}[/]")
    console.print(f"  [cyan]     ./conductor.py create --specs centos:9 --count 1[/]")


def show_cloudinit_logs(
    vm_name: str,
    lines: int
) -> None:
    """
    Show cloud-init logs for a VM.
    
    Args:
        vm_name: Name of the VM to check
        lines: Number of log lines to show (default: 50)
    """
    console.print(Panel.fit(
        f"[bold cyan]Cloud-Init Logs: {vm_name}[/]",
        border_style="cyan"
    ))
    
    config = load_config()
    host_config = config.get("host", {})
    vms_config = config.get("vms", {})
    ssh_key_path = host_config.get("ssh_key_path", f"{os.path.expanduser('~')}/.ssh/conductor-test-key")
    vm_user = vms_config.get("user", "conductor")
    
    # Get VM IP
    ip = get_vm_ip(vm_name)
    if not ip:
        console.print(f"[red]✗[/] No IP address (VM may not be running)")
        console.print(f"[dim]Check VM status: ./conductor.py status[/]")
        return
    
    console.print(f"[dim]VM IP: {ip}[/]\n")
    
    # Get cloud-init logs via SSH
    log_cmd = [
        "ssh",
        "-i", ssh_key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-q",
        f"{vm_user}@{ip}",
        f"tail -{lines} /var/log/cloud-init.log 2>/dev/null || echo 'ERROR: Cannot access cloud-init log file'"
    ]
    
    result = run_command(log_cmd, capture=True, check=False, timeout=15)
    
    if result.returncode != 0:
        console.print(f"[red]✗[/] Cannot connect via SSH")
        console.print(f"[dim]  → Cloud-init may still be running (SSH not ready yet)[/]")
        console.print(f"[dim]  → Check VM console: sudo virsh console {vm_name}[/]")
        return
    
    if "ERROR:" in result.stdout:
        console.print(f"[red]{result.stdout}[/]")
        console.print(f"[dim]  → Try checking VM console: sudo virsh console {vm_name}[/]")
        return
    
    if not result.stdout.strip():
        console.print(f"[yellow]⚠[/] No log output (cloud-init may not have started yet)")
        return
    
    # Display logs with syntax highlighting for errors/warnings
    console.print("[dim]Cloud-init log output:[/]\n")
    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # Color code based on log level
        if any(keyword in line.lower() for keyword in ['error', 'failed', 'failure', 'exception']):
            console.print(f"[red]{line}[/]")
        elif any(keyword in line.lower() for keyword in ['warning', 'warn']):
            console.print(f"[yellow]{line}[/]")
        elif any(keyword in line.lower() for keyword in ['info', 'started', 'completed', 'finished']):
            console.print(f"[green]{line}[/]")
        else:
            console.print(f"[dim]{line}[/]")
    
    console.print(f"\n[dim]Showing last {lines} lines. Use --lines to show more.[/]")


def _start_single_vm(vm_name: str) -> None:
    """
    Start a single VM.
    
    Handles missing cloud-init ISO files by either recreating them
    or detaching them from the VM definition (since they're only
    needed for first boot).
    
    Args:
        vm_name: Name of the VM to start
    """
    console.print(f"[cyan]Starting {vm_name}...[/]")
    
    # Check if cloud-init ISO is missing and handle it
    _ensure_cloudinit_iso_or_detach(vm_name)
    
    result = run_command(
        ["virsh", "start", vm_name],
        sudo=True,
        check=False
    )
    
    if result.returncode == 0:
        console.print(f"  [green]✓[/] {vm_name} started")
    else:
        console.print(f"  [red]✗[/] {vm_name} failed to start")
        if result.stderr:
            error_msg = result.stderr.strip()
            console.print(f"  [dim]Error: {error_msg[:200]}[/]")
            
            # Provide helpful guidance for common errors
            if "Cannot access storage file" in error_msg and "cloud-init.iso" in error_msg:
                console.print(f"  [yellow]⚠[/] Cloud-init ISO file is missing")
                console.print(f"  [dim]  → The cloud-init ISO was likely deleted[/]")
                console.print(f"  [dim]  → Try running: ./conductor.py start {vm_name} again[/]")
                console.print(f"  [dim]  → Or manually detach it: sudo virsh detach-disk {vm_name} hdb --config[/]")


def _destroy_single_vm(vm_name: str, image_dir: str) -> None:
    """
    Destroy a single VM.
    
    Args:
        vm_name: Name of the VM to destroy
        image_dir: Directory where VM disk images are stored
    """
    console.print(f"[cyan]Destroying {vm_name}...[/]")
    
    # Check if VM is running
    result = run_command(
        ["virsh", "domstate", vm_name],
        sudo=True,
        check=False
    )
    
    state = result.stdout.strip() if result.returncode == 0 else "unknown"
    
    if state == "running":
        console.print(f"  [dim]Stopping VM...[/]")
        run_command(
            ["virsh", "destroy", vm_name],
            sudo=True,
            check=False
        )
    
    # Undefine VM and remove storage
    console.print(f"  [dim]Removing VM definition and storage...[/]")
    run_command(
        ["virsh", "undefine", vm_name, "--remove-all-storage"],
        sudo=True,
        check=False
    )
    
    # Clean up any remaining disk images
    disk_path = Path(image_dir) / f"{vm_name}.qcow2"
    if disk_path.exists():
        try:
            run_command(
                ["rm", "-f", str(disk_path)],
                sudo=True,
                check=False
            )
        except Exception:
            pass  # Ignore errors if file doesn't exist
    
    console.print(f"  [green]✓[/] {vm_name} destroyed")
