#!/usr/bin/env python3
"""
Multi-tenant startup script.

This script runs the restaurant bot application for a specific tenant
or lists available tenants.

Usage:
    # List available tenants
    python run_tenant.py --list

    # Run for a specific tenant
    python run_tenant.py sammys

    # Run with custom port
    python run_tenant.py sammys --port 8001

    # Run with reload for development
    python run_tenant.py sammys --reload
"""

import argparse
import json
import os
import sys
from pathlib import Path


def load_tenants_config(config_path: str = "tenants.json") -> dict:
    """Load tenant configuration from JSON file."""
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Tenant config not found: {config_path}")
        sys.exit(1)

    with open(path, "r") as f:
        return json.load(f)


def list_tenants(config: dict) -> None:
    """Print available tenants."""
    print("\nAvailable tenants:")
    print("-" * 50)

    default = config.get("default_tenant", "")

    for slug, tenant in config.get("tenants", {}).items():
        default_marker = " (default)" if slug == default else ""
        print(f"  {slug}{default_marker}")
        print(f"    Name: {tenant.get('name', slug)}")
        print(f"    Port: {tenant.get('port', 8000)}")
        print(f"    Database: {tenant.get('database_url', 'N/A')}")
        print()


def run_tenant(
    tenant_slug: str,
    config: dict,
    host: str = "0.0.0.0",
    port: int = None,
    reload: bool = False,
) -> None:
    """Run the application for a specific tenant."""
    tenants = config.get("tenants", {})

    if tenant_slug not in tenants:
        print(f"Error: Unknown tenant '{tenant_slug}'")
        print("Use --list to see available tenants")
        sys.exit(1)

    tenant = tenants[tenant_slug]
    tenant_port = port or tenant.get("port", 8000)
    database_url = tenant.get("database_url", f"sqlite:///./data/{tenant_slug}.db")

    # Set environment variables for this tenant
    os.environ["TENANT_SLUG"] = tenant_slug
    os.environ["DATABASE_URL"] = database_url
    os.environ["TENANT_PORT"] = str(tenant_port)

    print(f"\n{'=' * 50}")
    print(f"Starting: {tenant.get('name', tenant_slug)}")
    print(f"Tenant:   {tenant_slug}")
    print(f"Port:     {tenant_port}")
    print(f"Database: {database_url}")
    print(f"{'=' * 50}\n")

    # Ensure data directory exists
    if database_url.startswith("sqlite:///./"):
        db_path = database_url.replace("sqlite:///./", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    # Import and run
    import uvicorn

    # For now, run the existing app with environment-based configuration
    # The app will read TENANT_SLUG and DATABASE_URL from environment
    uvicorn.run(
        "sandwich_bot.main:app",
        host=host,
        port=tenant_port,
        reload=reload,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run the restaurant bot for a specific tenant"
    )
    parser.add_argument(
        "tenant",
        nargs="?",
        help="Tenant slug to run (e.g., 'sammys')",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available tenants",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="tenants.json",
        help="Path to tenant configuration file (default: tenants.json)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        help="Port to run on (overrides tenant config)",
    )
    parser.add_argument(
        "--reload",
        "-r",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    config = load_tenants_config(args.config)

    if args.list:
        list_tenants(config)
        return

    if not args.tenant:
        # Use default tenant if available
        default = config.get("default_tenant")
        if default:
            args.tenant = default
            print(f"Using default tenant: {default}")
        else:
            print("Error: No tenant specified and no default configured")
            print("Use --list to see available tenants")
            sys.exit(1)

    run_tenant(
        args.tenant,
        config,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
