"""
Image detection and management functions.

Handles checking for base images, scanning directories for available images,
and determining image paths for different distributions.
"""

import re
import subprocess
from pathlib import Path


def check_image_exists(image_path: Path) -> bool:
    """
    Check if an image file exists, handling permission issues.
    
    Tries multiple methods to check file existence:
    1. Path.exists() - standard Python method
    2. Path.stat() - may work with limited permissions
    3. ls command - works even with limited directory permissions
    4. test command - alternative file check
    5. sudo test - if other methods fail
    
    Args:
        image_path: Path to the image file to check
    
    Returns:
        True if image exists, False otherwise
    """
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
    
    # Try using ls command on the specific file
    # (works even with limited directory permissions)
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
    
    # Try with sudo if the above didn't work
    # (non-interactive, may prompt for password)
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


def get_base_image_path(
    distro: str,
    version: str,
    image_dir: str
) -> Path | None:
    """
    Get the base image path for a distribution and version.
    
    Args:
        distro: Distribution name (fedora, debian, ubuntu, centos, rhel, suse)
        version: Version string (e.g., "42", "24.04", "10.0")
        image_dir: Directory where base images are stored
    
    Returns:
        Path object for the base image, or None if distribution is unknown
    """
    image_path = Path(image_dir)
    
    if distro == "fedora":
        return image_path / f"fedora-cloud-base-{version}.qcow2"
    elif distro == "debian":
        return image_path / f"debian-cloud-base-{version}.qcow2"
    elif distro == "ubuntu":
        version_key = version.replace(".", "_")
        return image_path / f"ubuntu-cloud-base-{version_key}.qcow2"
    elif distro == "centos":
        return image_path / f"centos-cloud-base-{version}.qcow2"
    elif distro == "rhel":
        # Use actual RHEL naming pattern: rhel-10.0-x86_64-kvm.qcow2
        return image_path / f"rhel-{version}-x86_64-kvm.qcow2"
    elif distro == "suse":
        version_key = version.replace(".", "_")
        if version.startswith("sles"):
            version_key = f"sles_{version_key[4:]}"
        return image_path / f"suse-cloud-base-{version_key}.qcow2"
    else:
        return None


def scan_available_images(image_dir: str) -> dict[str, list[str]]:
    """
    Scan image directory for available base images and return detected versions.
    
    Scans the specified directory for .qcow2 files matching distribution
    naming patterns and extracts version information.
    
    Args:
        image_dir: Directory to scan for images
    
    Returns:
        Dictionary mapping distribution names to lists of detected versions
    """
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
        "suse": re.compile(
            r'suse-cloud-base-((?:sles_)?\d+(?:_\d+)?|tumbleweed)\.qcow2'
        )
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
                        # Pattern with minor version:
                        # rhel-10.0-x86_64-kvm.qcow2 or rhel-cloud-base-10_0.qcow2
                        version = f"{match.group(1)}.{match.group(2)}"
                    else:
                        # Pattern with major version only:
                        # rhel-10-x86_64-kvm.qcow2 or rhel-cloud-base-10.qcow2
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

