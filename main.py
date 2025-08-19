#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "python-decouple>=3.8",
#     "sh>=2.2.2",
# ]
# [tool.uv]
# exclude-newer = "2025-08-31T00:00:00Z"
# ///

# pyright: reportMissingImports=false

"""
Usage:
    hello <get|ls|env|greet>

Args:
    get: Make a GET request to GitHub API
    ls: List files in current directory
    env: Show environment variable
    greet: Show welcome message

Note:
    Demo for uv's PEP 723 script support with various dependencies.

    Dependencies get cached in `uv cache dir`
    e.g., ~/Library/Caches/uv/environments-v2/hello-8969d74899f61209
"""

import httpx
import sys
from pathlib import Path
from sh import ErrorReturnCode, ls


def main():
    # Use match-case to handle different commands
    match sys.argv[1] if len(sys.argv) > 1 else "help":
        case "get":
            # Make a GET request using httpx
            response = httpx.get("https://api.github.com")
            print(f"Response from GitHub API: {response.status_code}")

        case "ls":
            # Run the ls command using sh
            try:
                output = ls("-l")
                print(f"Output of 'ls -l':\n{output}")
            except ErrorReturnCode as e:
                print(f"Error running command: {e}")

        case "env":
            # Get an environment variable using decouple
            env_file = Path.cwd() / '.env'
            if env_file.exists():
                from decouple import Config, RepositoryEnv
                config = Config(RepositoryEnv(env_file))
                my_var = config("HELLO", default="world")
            else:
                from decouple import config
                my_var = config("HELLO", default="world")
            print(f"Hello, {my_var}!")

        case "greet":
            # Print a welcome message
            print("Welcome to the greet script!")

        case _:
            print(__doc__.strip())


if __name__ == "__main__":
    main()
