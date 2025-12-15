"""
Utility functions for running commands and scripts.

Provides wrappers around subprocess for executing system commands
and scripts with proper error handling.
"""

import os
import subprocess
from pathlib import Path

from rich.console import Console

from conductor.config import SCRIPTS_DIR

console = Console()


def run_command(
    cmd: list[str],
    capture: bool = True,
    check: bool = True,
    sudo: bool = False,
    **kwargs
) -> subprocess.CompletedProcess:
    """
    Run a command and return the result.
    
    Args:
        cmd: Command and arguments as a list
        capture: Whether to capture stdout/stderr
        check: Whether to raise exception on non-zero exit
        sudo: Whether to run with sudo (if not root)
        **kwargs: Additional arguments to pass to subprocess.run
    
    Returns:
        CompletedProcess object with command results
    
    Raises:
        subprocess.CalledProcessError: If check=True and command fails
    """
    if sudo and os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=check,
            **kwargs
        )
        return result
    except subprocess.CalledProcessError as e:
        if capture:
            console.print(f"[red]Command failed:[/] {' '.join(cmd)}")
            if e.stdout:
                console.print(f"[dim]stdout:[/] {e.stdout}")
            if e.stderr:
                console.print(f"[dim]stderr:[/] {e.stderr}")
        raise


def run_script(
    script_name: str,
    args: list[str] = None,
    **kwargs
) -> subprocess.CompletedProcess:
    """
    Run a script from the scripts directory.
    
    Args:
        script_name: Name of the script file in scripts directory
        args: Optional list of arguments to pass to the script
        **kwargs: Additional arguments to pass to run_command
    
    Returns:
        CompletedProcess object with script results
    
    Raises:
        FileNotFoundError: If script doesn't exist
        subprocess.CalledProcessError: If script execution fails
    """
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")
    
    cmd = ["bash", str(script_path)]
    if args:
        cmd.extend(args)
    
    return run_command(cmd, **kwargs)

