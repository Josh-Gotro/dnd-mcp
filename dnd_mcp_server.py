#!/usr/bin/env python3
"""
D&D Knowledge Navigator - Main server entry point.

This script starts the FastMCP server that provides D&D 5e information
through the Model Context Protocol (MCP).
"""

import logging
import sys
import traceback
import os
from mcp.server.fastmcp import FastMCP

# Import from our reorganized structure
from src.core import api_helpers
from src.core import formatters
from src.core import prompts
from src.core import tools
from src.core import resources
from src.core.cache import APICache
from src.core.supabase_client import SupabaseClient

# Configure more detailed logging
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "dnd_mcp_server.log")

# Configure logging with both console and file output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for the D&D Knowledge Navigator server."""
    # Add debug output
    print("Starting D&D Knowledge Navigator with FastMCP...", file=sys.stderr)
    print(f"Python version: {sys.version}", file=sys.stderr)
    print(f"Current directory: {os.getcwd()}", file=sys.stderr)
    print(
        f"Logs will be saved to: {os.path.abspath(log_file)}", file=sys.stderr)

    try:
        # Create FastMCP server
        print("Creating FastMCP server...", file=sys.stderr)
        app = FastMCP("dnd-knowledge-navigator")
        print("FastMCP server created successfully", file=sys.stderr)

        # Create shared cache with 24-hour TTL and persistence
        cache_dir = os.path.join(os.path.dirname(__file__), "cache")
        cache = APICache(ttl_hours=24, persistent=True, cache_dir=cache_dir)
        print(
            f"API cache initialized (24-hour TTL, persistent cache in {cache_dir})", file=sys.stderr)

        # Register D&D 5e API components
        resources.register_resources(app, cache)
        tools.register_tools(app, cache)
        prompts.register_prompts(app)

        # Initialize Supabase client for campaign database (optional)
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")

        if supabase_url and supabase_key:
            print("Initializing Supabase client for campaign database...", file=sys.stderr)
            supabase_client = SupabaseClient(
                api_url=supabase_url,
                api_key=supabase_key,
                cache=cache,
                cache_prefix="campaign"
            )

            # Verify connection
            health = supabase_client.health_check()
            if health.get("connected"):
                print("Supabase connected successfully", file=sys.stderr)
                # Register campaign tools
                tools.register_campaign_tools(app, supabase_client)
            else:
                print(f"Warning: Supabase connection failed: {health.get('error')}", file=sys.stderr)
                print("Campaign tools will not be available", file=sys.stderr)
        else:
            print("Supabase credentials not found in environment", file=sys.stderr)
            print("Set SUPABASE_URL and SUPABASE_KEY to enable campaign tools", file=sys.stderr)

        # Run the app
        print("Running FastMCP app...", file=sys.stderr)
        app.run()
        print("App run completed", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


# For direct execution, we use the main() function
if __name__ == "__main__":
    sys.exit(main())
