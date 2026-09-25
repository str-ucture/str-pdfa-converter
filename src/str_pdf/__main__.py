"""Entry point for `python -m str_pdf`, the `str-pdf` command, and the PyInstaller bundle."""

import sys


def main() -> None:
    if "--smoke-check" in sys.argv:
        from str_pdf.smoke import main as smoke_check
        smoke_check()
    else:
        from str_pdf.app import main as run_app
        run_app()


if __name__ == "__main__":
    main()
