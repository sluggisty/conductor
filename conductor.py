#!/usr/bin/env python3
"""
Conductor - VM Orchestration Tool

This tool manages VMs for testing. It provides commands to list available
distributions and versions, and check for base images.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.table import Table

console = Console()

# Default paths
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.yaml"


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return yaml.safe_load(f)
    return {}


def check_image_exists(image_path: Path) -> bool:
    """Check if an image file exists, handling permission issues."""
    # First try normal path.exists() - this should work even without read permissions
    try:
        if image_path.exists():
            return True
    except (OSError, PermissionError):
        pass
    
    # Try using stat() which might work even without read permissions
    try:
        image_path.stat()
        return True
    except (OSError, PermissionError, FileNotFoundError):
        pass
    
    # Try using ls command on the specific file (works even with limited directory permissions)
    try:
        result = subprocess.run(
            ["ls", str(image_path)],
            capture_output=True,
            check=False,
            timeout=2
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        pass
    
    # Try with test command
    try:
        result = subprocess.run(
            ["test", "-f", str(image_path)],
            capture_output=True,
            check=False,
            timeout=2
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        pass
    
    # Try with sudo if the above didn't work (non-interactive, may prompt for password)
    try:
        result = subprocess.run(
            ["sudo", "-n", "test", "-f", str(image_path)],
            capture_output=True,
            check=False,
            timeout=2
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        pass
    
    return False


def scan_available_images(image_dir: str) -> dict[str, list[str]]:
    """Scan image directory for available base images and return detected versions."""
    detected = {
        "fedora": [],
        "debian": [],
        "ubuntu": [],
        "centos": [],
        "rhel": [],
        "suse": []
    }
    
    # Pattern matching for different distributions
    patterns = {
        "fedora": re.compile(r'fedora-cloud-base-(\d+)\.qcow2'),
        "debian": re.compile(r'debian-cloud-base-(\d+)\.qcow2'),
        "ubuntu": re.compile(r'ubuntu-cloud-base-(\d+)_(\d+)\.qcow2'),
        "centos": re.compile(r'centos-cloud-base-(\d+)\.qcow2'),
        "rhel": [
            re.compile(r'rhel-(\d+)\.(\d+)-x86_64-kvm\.qcow2'),  # rhel-10.0-x86_64-kvm.qcow2
            re.compile(r'rhel-(\d+)-x86_64-kvm\.qcow2'),  # rhel-10-x86_64-kvm.qcow2
            re.compile(r'rhel-cloud-base-(\d+)(?:_(\d+))?\.qcow2'),  # Legacy: rhel-cloud-base-10_0.qcow2
        ],
        "suse": re.compile(r'suse-cloud-base-((?:sles_)?\d+(?:_\d+)?|tumbleweed)\.qcow2')
    }
    
    # Try to get list of files - first try normal glob, then try ls command
    files_to_check = []
    image_path = Path(image_dir)
    
    try:
        # Try normal glob first
        if image_path.exists():
            files_to_check = list(image_path.glob("*.qcow2"))
    except (OSError, PermissionError):
        pass
    
    # If glob didn't work, try using ls command
    if not files_to_check:
        try:
            result = subprocess.run(
                ["ls", "-1", str(image_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.endswith(".qcow2"):
                        files_to_check.append(Path(image_dir) / line.strip())
        except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
    
    # If that didn't work, try with sudo
    if not files_to_check:
        try:
            result = subprocess.run(
                ["sudo", "-n", "ls", "-1", str(image_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.endswith(".qcow2"):
                        files_to_check.append(Path(image_dir) / line.strip())
        except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
    
    try:
        for img_file in files_to_check:
            filename = img_file.name if isinstance(img_file, Path) else img_file
            
            # Check Fedora
            match = patterns["fedora"].match(filename)
            if match:
                detected["fedora"].append(match.group(1))
                continue
            
            # Check Debian
            match = patterns["debian"].match(filename)
            if match:
                detected["debian"].append(match.group(1))
                continue
            
            # Check Ubuntu
            match = patterns["ubuntu"].match(filename)
            if match:
                version = f"{match.group(1)}.{match.group(2)}"
                detected["ubuntu"].append(version)
                continue
            
            # Check CentOS
            match = patterns["centos"].match(filename)
            if match:
                detected["centos"].append(match.group(1))
                continue
            
            # Check RHEL - try multiple patterns
            for pattern in patterns["rhel"]:
                match = pattern.match(filename)
                if match:
                    if len(match.groups()) == 2 and match.group(2):
                        # Pattern with minor version: rhel-10.0-x86_64-kvm.qcow2 or rhel-cloud-base-10_0.qcow2
                        version = f"{match.group(1)}.{match.group(2)}"
                    else:
                        # Pattern with major version only: rhel-10-x86_64-kvm.qcow2 or rhel-cloud-base-10.qcow2
                        version = match.group(1)
                    detected["rhel"].append(version)
                    break
            else:
                continue
            continue
            
            # Check SUSE
            match = patterns["suse"].match(filename)
            if match:
                version_key = match.group(1)
                if version_key == "tumbleweed":
                    detected["suse"].append("tumbleweed")
                elif version_key.startswith("sles_"):
                    # Convert sles_15_5 to sles15.5
                    version = version_key.replace("sles_", "sles").replace("_", ".")
                    detected["suse"].append(version)
                else:
                    # Convert 15_5 to 15.5
                    version = version_key.replace("_", ".")
                    detected["suse"].append(version)
                continue
    except PermissionError:
        # Can't read directory, return empty
        pass
    
    # Sort and deduplicate
    for distro in detected:
        detected[distro] = sorted(set(detected[distro]), reverse=True)
    
    return detected


# CLI Commands
@click.group()
@click.version_option(version="0.1.0", prog_name="conductor")
def cli():
    """
    Conductor - VM management and testing tool.
    
    This tool helps you manage and test across multiple Linux distributions.
    """
    pass


@cli.command("list-versions")
@click.option("--scan", is_flag=True, help="Scan image directory and show detected images")
@click.option("--debug", is_flag=True, help="Show debug information about file checks")
def list_versions(scan: bool, debug: bool):
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
                    if distro == "fedora":
                        img_file = f"fedora-cloud-base-{version}.qcow2"
                    elif distro == "debian":
                        img_file = f"debian-cloud-base-{version}.qcow2"
                    elif distro == "ubuntu":
                        version_key = version.replace(".", "_")
                        img_file = f"ubuntu-cloud-base-{version_key}.qcow2"
                    elif distro == "centos":
                        img_file = f"centos-cloud-base-{version}.qcow2"
                    elif distro == "rhel":
                        version_key = version.replace(".", "_")
                        img_file = f"rhel-cloud-base-{version_key}.qcow2"
                    elif distro == "suse":
                        version_key = version.replace(".", "_")
                        if version.startswith("sles"):
                            version_key = f"sles_{version_key[4:]}"
                        img_file = f"suse-cloud-base-{version_key}.qcow2"
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
        fedora_versions = distributions["fedora"].get("available_versions", {})
        table = Table(title="Available Fedora Versions")
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
        
        for version, name in sorted(fedora_versions.items(), key=sort_key, reverse=True):
            base_image = Path(image_dir) / f"fedora-cloud-base-{version}.qcow2"
            exists = check_image_exists(base_image)
            status = "[green]✓[/]" if exists else "[red]✗[/]"
            table.add_row(str(version), name, status)
        
        console.print(table)
        console.print()
    
    # Show Debian versions
    if "debian" in distributions:
        debian_versions = distributions["debian"].get("available_versions", {})
        table = Table(title="Available Debian Versions")
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
        
        for version, name in sorted(debian_versions.items(), key=sort_key, reverse=True):
            base_image = Path(image_dir) / f"debian-cloud-base-{version}.qcow2"
            exists = check_image_exists(base_image)
            status = "[green]✓[/]" if exists else "[red]✗[/]"
            table.add_row(str(version), name, status)
        
        console.print(table)
        console.print()
    
    # Show Ubuntu versions
    if "ubuntu" in distributions:
        ubuntu_versions = distributions["ubuntu"].get("available_versions", {})
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
        
        for version, name in sorted(ubuntu_versions.items(), key=ubuntu_sort_key, reverse=True):
            version_key = version.replace(".", "_")
            base_image = Path(image_dir) / f"ubuntu-cloud-base-{version_key}.qcow2"
            exists = check_image_exists(base_image)
            status = "[green]✓[/]" if exists else "[red]✗[/]"
            table.add_row(str(version), name, status)
        
        console.print(table)
        console.print()
    
    # Show CentOS versions
    if "centos" in distributions:
        centos_versions = distributions["centos"].get("available_versions", {})
        table = Table(title="Available CentOS Versions")
        table.add_column("Version", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Base Image", justify="center")
        
        # Sort CentOS versions (they're like "9", "8", "7")
        def centos_sort_key(item):
            version = item[0]
            if isinstance(version, str) and version.isdigit():
                return int(version)
            return 0
        
        for version, name in sorted(centos_versions.items(), key=centos_sort_key, reverse=True):
            base_image = Path(image_dir) / f"centos-cloud-base-{version}.qcow2"
            exists = check_image_exists(base_image)
            status = "[green]✓[/]" if exists else "[red]✗[/]"
            table.add_row(str(version), name, status)
        
        console.print(table)
        console.print()
    
    # Show RHEL versions
    if "rhel" in distributions:
        rhel_versions = distributions["rhel"].get("available_versions", {})
        table = Table(title="Available RHEL Versions")
        table.add_column("Version", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Base Image", justify="center")
        table.add_column("Note", style="yellow")
        
        # Sort RHEL versions (they're like "10.1", "10.0", "10", "9.4", "9.3", "9", "8.10", "8", "7.9", "7")
        def rhel_sort_key(item):
            version = item[0]
            if isinstance(version, str):
                if "." in version:
                    # Minor release: "10.1" -> 10001, "9.4" -> 904, "8.10" -> 810
                    parts = version.split(".")
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        return int(parts[0]) * 1000 + int(parts[1])
                elif version.isdigit():
                    # Major version: "10" -> 10000, "9" -> 9000 (so it sorts after minor releases)
                    return int(version) * 1000
            return 0
        
        for version, name in sorted(rhel_versions.items(), key=rhel_sort_key, reverse=True):
            exists = False
            base_image = None
            
            # Try the actual naming pattern first: rhel-10.0-x86_64-kvm.qcow2
            if "." in version:
                # Minor version: 10.0 -> rhel-10.0-x86_64-kvm.qcow2
                actual_image = Path(image_dir) / f"rhel-{version}-x86_64-kvm.qcow2"
                if check_image_exists(actual_image):
                    exists = True
                    base_image = actual_image
            else:
                # Major version only: 10 -> rhel-10-x86_64-kvm.qcow2
                actual_image = Path(image_dir) / f"rhel-{version}-x86_64-kvm.qcow2"
                if check_image_exists(actual_image):
                    exists = True
                    base_image = actual_image
            
            # Try legacy naming pattern if the actual one doesn't exist
            if not exists:
                version_key = version.replace(".", "_")
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
    
    # Show SUSE versions
    if "suse" in distributions:
        suse_versions = distributions["suse"].get("available_versions", {})
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
        
        for version, name in sorted(suse_versions.items(), key=suse_sort_key, reverse=True):
            version_key = version.replace(".", "_")
            if version.startswith("sles"):
                version_key = f"sles_{version_key[4:]}"
            base_image = Path(image_dir) / f"suse-cloud-base-{version_key}.qcow2"
            exists = check_image_exists(base_image)
            status = "[green]✓[/]" if exists else "[red]✗[/]"
            note = "[yellow]Requires subscription[/]" if version.startswith("sles") and not exists else ""
            table.add_row(str(version), name, status, note)
        
        console.print(table)
        console.print()
    
    console.print(f"[dim]Base images directory: {image_dir}[/]")
    console.print("[dim]✓ = Image exists, ✗ = Image not found[/]")
    console.print("")


if __name__ == "__main__":
    cli()

