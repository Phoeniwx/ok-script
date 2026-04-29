"""Entry point for python -m ok.cli."""

from ok.cli.bootstrap import prepare_cli_environment

prepare_cli_environment()

from ok.cli.cli import cli

if __name__ == "__main__":
    cli()
