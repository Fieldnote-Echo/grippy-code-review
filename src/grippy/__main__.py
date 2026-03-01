# SPDX-License-Identifier: MIT
"""Package entry point — run Grippy via `python -m grippy`.

Using `python -m grippy` instead of `python -m grippy.review` avoids
a RuntimeWarning caused by __init__.py eagerly importing grippy.review
before the -m mechanism executes it as __main__.
"""

import argparse

from grippy.review import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grippy AI code review agent")
    parser.add_argument(
        "--profile",
        choices=["general", "security", "strict-security"],
        default=None,
        help="Security profile (overrides GRIPPY_PROFILE env var)",
    )
    args = parser.parse_args()
    main(profile=args.profile)
