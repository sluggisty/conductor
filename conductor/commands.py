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
        try:
            shutil.rmtree(cloudinit_path)
            console.print(f"[green]✓[/] Removed {cloudinit_dir}")
        except Exception as e:
            console.print(f"[yellow]⚠[/] Failed to remove cloud-init directory: {e}")
    
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


def _start_single_vm(vm_name: str) -> None:
    """
    Start a single VM.
    
    Args:
        vm_name: Name of the VM to start
    """
    console.print(f"[cyan]Starting {vm_name}...[/]")
    
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
            console.print(f"  [dim]Error: {result.stderr[:200]}[/]")


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
