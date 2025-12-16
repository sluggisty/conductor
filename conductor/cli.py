"""
CLI setup and entry point.

Defines the Click command group and registers all commands.
"""

import click

from conductor import __version__
from conductor.commands import (
    create_all_vms,
    create_vms,
    destroy_vms,
    list_versions,
    run_snail_on_vms,
    shutdown_vms,
    show_status,
    start_vms,
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
def status(as_json: bool):
    """Show status of all test VMs."""
    show_status(as_json)


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


