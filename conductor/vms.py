"""
VM management functions.

Handles listing VMs, checking for available distributions,
and managing VM-related operations.
"""

from pathlib import Path
from typing import Any

from conductor.config import load_config
from conductor.images import check_image_exists, get_base_image_path
from conductor.utils import run_command


def get_vm_list() -> list[str]:
    """
    Get list of all conductor-test VMs.
    
    Queries libvirt for all VMs and filters for those matching
    the conductor-test naming pattern.
    
    Returns:
        List of VM names, sorted by distro, version, then number
    """
    config = load_config()
    prefix = config.get("vms", {}).get("name_prefix", "conductor-test")
    
    result = run_command(
        ["virsh", "list", "--all", "--name"],
        sudo=True,
        check=False
    )
    
    if result.returncode != 0:
        return []
    
    vms = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        # Match pattern: conductor-test-<distro>-<version>-<number>
        if line.startswith(prefix) and "-" in line[len(prefix):]:
            vms.append(line)
    
    # Sort by distro, version, then number
    def sort_key(vm_name: str) -> tuple:
        parts = vm_name.split("-")
        if len(parts) >= 4:
            # Format: prefix-distro-version-number
            try:
                distro = parts[-3]
                version = parts[-2]
                number = int(parts[-1])
                # Convert version to int if possible for sorting
                try:
                    version_num = float(version)
                except ValueError:
                    version_num = 0
                return (distro, version_num, number)
            except (ValueError, IndexError):
                pass
        return ("", 0, 0)
    
    return sorted(vms, key=sort_key, reverse=True)


def get_available_distro_versions(
    config: dict[str, Any],
    image_dir: str
) -> dict[str, str]:
    """
    Get the first available version for each distribution that has base images.
    
    For each distribution, tries the default version first, then searches
    through all available versions to find one with a downloaded base image.
    
    Args:
        config: Configuration dictionary
        image_dir: Directory where base images are stored
    
    Returns:
        Dictionary mapping distribution names to version strings
    """
    distributions = config.get("vms", {}).get("distributions", {})
    available = {}
    
    for distro_name, distro_config in distributions.items():
        available_versions = distro_config.get("available_versions", {})
        
        # Try default version first
        default_version = distro_config.get("default_version")
        found_version = None
        
        if default_version and default_version in available_versions:
            # Check if default version's image exists
            if _check_distro_version_image(distro_name, default_version, image_dir):
                found_version = default_version
        
        # If default not available, try all versions in order
        if not found_version:
            # Sort versions appropriately for each distro
            versions_list = list(available_versions.keys())
            
            if distro_name in ("fedora", "debian", "centos"):
                # Sort numerically (e.g., 42, 41, 40, 12, 11, 10)
                def numeric_sort(v):
                    if isinstance(v, str) and v.isdigit():
                        return int(v)
                    elif isinstance(v, int):
                        return v
                    return 0
                
                try:
                    versions_list.sort(key=numeric_sort, reverse=True)
                except (ValueError, TypeError):
                    versions_list.sort(reverse=True)
            elif distro_name == "ubuntu":
                # Sort by version number (24.04, 22.04, etc.)
                def ubuntu_sort(v):
                    if isinstance(v, str) and "." in v:
                        parts = v.split(".")
                        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                            return int(parts[0]) * 100 + int(parts[1])
                    return 0
                versions_list.sort(key=ubuntu_sort, reverse=True)
            elif distro_name == "rhel":
                # Sort RHEL versions
                def rhel_sort(v):
                    if isinstance(v, str):
                        if "." in v:
                            parts = v.split(".")
                            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                                return int(parts[0]) * 1000 + int(parts[1])
                        elif v.isdigit():
                            return int(v) * 1000
                    return 0
                versions_list.sort(key=rhel_sort, reverse=True)
            elif distro_name == "suse":
                # Sort SUSE versions
                def suse_sort(v):
                    if isinstance(v, str):
                        if v.startswith("sles"):
                            num = v[4:].replace(".", "")
                            if num.isdigit():
                                return 20000 + int(num)
                        elif v == "tumbleweed":
                            return 30000
                        elif "." in v:
                            parts = v.split(".")
                            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                                return int(parts[0]) * 100 + int(parts[1])
                    return 0
                versions_list.sort(key=suse_sort, reverse=True)
            
            # Find first available version
            for version in versions_list:
                if _check_distro_version_image(distro_name, version, image_dir):
                    found_version = version
                    break
        
        if found_version:
            available[distro_name] = found_version
    
    return available


def _check_distro_version_image(
    distro: str,
    version: str,
    image_dir: str
) -> bool:
    """
    Check if a base image exists for a distribution and version.
    
    Args:
        distro: Distribution name (fedora, debian, ubuntu, centos, rhel, suse)
        version: Version string (e.g., "42", "24.04", "10.0")
        image_dir: Directory where base images are stored
    
    Returns:
        True if the base image exists, False otherwise
    """
    base_image = get_base_image_path(distro, version, image_dir)
    if base_image is None:
        return False
    return check_image_exists(base_image)

