"""
Installation helper for MCP CLI integration
"""

import argparse
import sys
import subprocess
from pathlib import Path


def install_claude(enable_advanced_search=False):
    """Install to Claude Code using CLI command"""
    project_dir = Path.cwd().resolve()

    try:
        # Build command args
        cmd_args = [
            "claude", "mcp", "add",
            "--transport", "stdio",
            "--scope", "user",
            "gallica",
            "--",
            "uv", "--directory", str(project_dir), "run", "gallica-mcp"
        ]

        # Add advanced search flag if requested
        if enable_advanced_search:
            cmd_args.append("--enable-advanced-search")

        # Use the claude CLI to add the MCP server
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✓ Installed to Claude Code")
        print(f"  Project directory: {project_dir}")
        if enable_advanced_search:
            print(f"  Advanced search: enabled")
        if result.stdout:
            print(f"  {result.stdout.strip()}")
    except FileNotFoundError:
        raise Exception("'claude' command not found. Make sure Claude Code CLI is installed and in your PATH.")
    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to add MCP server: {e.stderr.strip() if e.stderr else str(e)}")


def install_codex(enable_advanced_search=False):
    """Install to Codex CLI using CLI command"""
    project_dir = Path.cwd().resolve()

    try:
        # Build command args
        cmd_args = [
            "codex", "mcp", "add",
            "gallica",
            "--",
            "uv", "--directory", str(project_dir), "run", "gallica-mcp"
        ]

        # Add advanced search flag if requested
        if enable_advanced_search:
            cmd_args.append("--enable-advanced-search")

        # Use the codex CLI to add the MCP server
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✓ Installed to Codex CLI")
        print(f"  Project directory: {project_dir}")
        if enable_advanced_search:
            print(f"  Advanced search: enabled")
        if result.stdout:
            print(f"  {result.stdout.strip()}")
    except FileNotFoundError:
        raise Exception("'codex' command not found. Make sure Codex CLI is installed and in your PATH.")
    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to add MCP server: {e.stderr.strip() if e.stderr else str(e)}")


def install_gemini(enable_advanced_search=False):
    """Install to Gemini CLI using CLI command"""
    project_dir = Path.cwd().resolve()

    try:
        # Build command args
        cmd_args = [
            "gemini", "mcp", "add",
            "gallica",
            "uv", "--directory", str(project_dir), "run", "gallica-mcp"
        ]

        # Add advanced search flag if requested
        if enable_advanced_search:
            cmd_args.append("--enable-advanced-search")

        # Use the gemini CLI to add the MCP server
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✓ Installed to Gemini CLI")
        print(f"  Project directory: {project_dir}")
        if enable_advanced_search:
            print(f"  Advanced search: enabled")
        if result.stdout:
            print(f"  {result.stdout.strip()}")
    except FileNotFoundError:
        raise Exception("'gemini' command not found. Make sure Gemini CLI is installed and in your PATH.")
    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to add MCP server: {e.stderr.strip() if e.stderr else str(e)}")


def main():
    """Install gallica MCP server to all detected CLIs"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Install Gallica MCP Server')
    parser.add_argument('--enable-advanced-search', action='store_true',
                        help='Enable the advanced_search_gallica tool with filter parameters')
    args = parser.parse_args()

    project_dir = Path.cwd().resolve()

    print(f"Installing gallica MCP server...")
    print(f"Working directory: {project_dir}")
    if args.enable_advanced_search:
        print(f"Advanced search: enabled\n")
    else:
        print(f"Advanced search: disabled\n")

    installed = []

    # Try installing to all CLIs
    try:
        install_claude(args.enable_advanced_search)
        installed.append("Claude Code")
    except Exception as e:
        print(f"⚠ Could not install to Claude Code: {e}")

    try:
        install_codex(args.enable_advanced_search)
        installed.append("Codex CLI")
    except Exception as e:
        print(f"⚠ Could not install to Codex CLI: {e}")

    try:
        install_gemini(args.enable_advanced_search)
        installed.append("Gemini CLI")
    except Exception as e:
        print(f"⚠ Could not install to Gemini CLI: {e}")

    if installed:
        print(f"\n✓ Successfully installed to: {', '.join(installed)}")
    else:
        print(f"\n✗ No CLIs were configured")
        sys.exit(1)

    if not args.enable_advanced_search:
        print(f"\n  To enable advanced search: run 'uv run gallica-mcp-install --enable-advanced-search'")

    print(f"\nRestart your CLI to use the server.")


if __name__ == "__main__":
    main()
