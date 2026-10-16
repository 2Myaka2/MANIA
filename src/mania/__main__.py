"""Delegate the Python module entry point to the interim CLI."""

from mania.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
