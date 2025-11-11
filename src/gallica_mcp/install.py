"""CLI installer for Gallica MCP server."""

import argparse
import json
import sys
from pathlib import Path


def install():
    """Install Gallica MCP server to Claude desktop configuration."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Install Gallica MCP Server')
    parser.add_argument('--enable-advanced-search', action='store_true',
                        help='Enable the advanced_search_gallica tool with filter parameters')
    args = parser.parse_args()

    # Determine config path based on platform
    if sys.platform == "darwin":
        config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        config_path = Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    else:  # Linux/Unix
        config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    # Load existing config or create new one
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = json.load(f)
    else:
        config = {}

    # Ensure mcpServers section exists
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    # Get the absolute path to server.py
    server_path = Path(__file__).parent / "server.py"

    # Build args list
    server_args = [
        "--directory",
        str(Path(__file__).parent.parent.parent),
        "run",
        "gallica-mcp"
    ]

    # Add advanced search flag if requested
    if args.enable_advanced_search:
        server_args.append("--enable-advanced-search")

    # Add Gallica MCP server configuration
    config["mcpServers"]["gallica"] = {
        "command": "uv",
        "args": server_args
    }

    # Create config directory if it doesn't exist
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write updated config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"✓ Gallica MCP server installed to {config_path}")
    print("\nConfiguration added:")
    print(json.dumps(config["mcpServers"]["gallica"], indent=2))
    if args.enable_advanced_search:
        print("\n✓ Advanced search enabled (advanced_search_gallica tool available)")
    else:
        print("\n  Advanced search disabled (only search_gallica tool available)")
        print("  To enable: run 'uv run gallica-mcp-install --enable-advanced-search'")
    print("\nRestart Claude desktop to use the Gallica MCP server.")


if __name__ == "__main__":
    install()
