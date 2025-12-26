"""
CLI setup and entry point.

Defines the Click command group and registers all commands.
"""

import click

from conductor import __version__
from conductor.commands import (
    check_cloudinit_status,
    create_all_vms,
    create_vms,
    debug_network,
    debug_snail_auth,
    debug_vm,
    destroy_vms,
    list_versions,
    run_snail_on_vms,
    show_cloudinit_logs,
    shutdown_vms,
    show_status,
    start_vms,
    wait_for_ssh,
)


@click.group()
@click.version_option(version=__version__, prog_name="conductor")
def cli():
    """
    Conductor - VM management and testing tool.
    
    This tool helps you manage and test across multiple Linux distributions.
    """
    pass


@cli.command("list-versions")
@click.option(
    "--scan",
    is_flag=True,
    help="Scan image directory and show detected images"
)
@click.option(
    "--debug",
    is_flag=True,
    help="Show debug information about file checks"
)
def list_versions_cmd(scan: bool, debug: bool):
    """List available distributions and their versions."""
    list_versions(scan, debug)


@cli.command()
@click.option(
    "--distro", "-d",
    help="Distribution: fedora, debian, ubuntu, centos, rhel, suse (default: fedora)"
)
@click.option(
    "--versions", "-v",
    help="Comma-separated versions (e.g., 42,41,40 for fedora or 12,11 for debian)"
)
@click.option(
    "--specs", "-s",
    help="VM specs in format 'distro:version' (e.g., 'fedora:42,debian:12')"
)
@click.option(
    "--count", "-n",
    default=5,
    help="Number of VMs per version (default: 5)"
)
@click.option(
    "--memory", "-m",
    default=2048,
    help="Memory per VM in MB"
)
@click.option(
    "--cpus", "-c",
    default=2,
    help="vCPUs per VM"
)
def create(
    distro: str,
    versions: str,
    specs: str,
    count: int,
    memory: int,
    cpus: int
):
    """Create test VMs for specified distributions and versions."""
    create_vms(distro, versions, specs, count, memory, cpus)


@cli.command()
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON"
)
@click.option(
    "--check-cloudinit",
    "check_cloudinit",
    is_flag=True,
    help="Check cloud-init completion status (slower but more informative)"
)
def status(as_json: bool, check_cloudinit: bool):
    """Show status of all test VMs."""
    show_status(as_json, check_cloudinit)


@cli.command("create-all")
@click.option(
    "--memory", "-m",
    default=2048,
    help="Memory per VM in MB"
)
@click.option(
    "--cpus", "-c",
    default=2,
    help="vCPUs per VM"
)
def create_all(memory: int, cpus: int):
    """Create one VM for each distribution that has available base images."""
    create_all_vms(memory, cpus)


@cli.command("run-snail")
@click.option(
    "--parallel", "-p",
    is_flag=True,
    help="Run commands in parallel (not yet implemented)"
)
@click.option(
    "--timeout", "-t",
    default=300,
    help="SSH command timeout in seconds (default: 300)"
)
@click.option(
    "--upload-url", "-u",
    help="Upload URL for snail-core to send data to (optional)"
)
def run_snail(parallel: bool, timeout: int, upload_url: str | None):
    """Run snail-core on all running VMs."""
    run_snail_on_vms(parallel, timeout, upload_url)


@cli.command("start")
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Don't ask for confirmation"
)
@click.option(
    "--vm",
    help="Start specific VM by name"
)
def start(force: bool, vm: str | None):
    """Start stopped VMs."""
    start_vms(force, vm)


@cli.command("shutdown")
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Don't ask for confirmation"
)
@click.option(
    "--vm",
    help="Shutdown specific VM by name"
)
def shutdown(force: bool, vm: str | None):
    """Shutdown (stop) VMs without deleting them."""
    shutdown_vms(force, vm)


@cli.command("destroy")
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Don't ask for confirmation"
)
@click.option(
    "--vm",
    help="Destroy specific VM by name"
)
def destroy(force: bool, vm: str | None):
    """Destroy (shutdown and remove) VMs."""
    destroy_vms(force, vm)


@cli.command("cloudinit-status")
@click.option(
    "--vm",
    help="Check specific VM by name (default: all running VMs)"
)
def cloudinit_status(vm: str | None):
    """Check cloud-init status for VMs."""
    check_cloudinit_status(vm)


@cli.command("cloudinit-logs")
@click.argument("vm_name", required=True)
@click.option(
    "--lines", "-n",
    default=50,
    help="Number of log lines to show (default: 50)"
)
def cloudinit_logs(vm_name: str, lines: int):
    """Show cloud-init logs for a specific VM."""
    show_cloudinit_logs(vm_name, lines)


@cli.command("debug")
@click.argument("vm_name", required=True)
def debug(vm_name: str):
    """Debug a VM using multiple methods without requiring login."""
    debug_vm(vm_name)


@cli.command("wait-ssh")
@click.argument("vm_name", required=True)
@click.option(
    "--timeout", "-t",
    default=300,
    help="Maximum time to wait in seconds (default: 300)"
)
@click.option(
    "--interval", "-i",
    default=5,
    help="How often to check in seconds (default: 5)"
)
def wait_ssh(vm_name: str, timeout: int, interval: int):
    """Wait for SSH to become available on a VM."""
    wait_for_ssh(vm_name, timeout, interval)


@cli.command("network-debug")
@click.argument("vm_name", required=True)
def network_debug_cmd(vm_name: str):
    """Debug network configuration for a VM."""
    from conductor.commands import debug_network
    
    debug_network(vm_name)


@cli.command("debug-snail")
@click.argument("vm_name", required=True)
def debug_snail(vm_name: str):
    """Debug snail-core authentication and API key issues on a VM."""
    debug_snail_auth(vm_name)


