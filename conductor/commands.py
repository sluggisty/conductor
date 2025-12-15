"""
CLI command implementations.

Contains all the Click command handlers for the Conductor CLI.
"""

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from conductor.config import SCRIPTS_DIR, load_config
from conductor.images import check_image_exists, get_base_image_path, scan_available_images
from conductor.utils import run_command
from conductor.vms import get_available_distro_versions, get_vm_list

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


def show_status(as_json: bool) -> None:
    """Show status of all test VMs."""
    vms = get_vm_list()
    
    if not vms:
        console.print("[yellow]No test VMs found[/]")
        return
    
    if as_json:
        import json
        data = [{"name": vm} for vm in vms]
        console.print_json(json.dumps(data))
        return
    
    console.print()
    table = Table(title="Conductor Test VMs")
    table.add_column("VM Name", style="cyan")
    
    for vm in vms:
        table.add_row(vm)
    
    console.print(table)
    console.print(f"\n[dim]Total: {len(vms)} VMs[/]")


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

