"""Package entry point — run Grippy via `python -m grippy`.

Using `python -m grippy` instead of `python -m grippy.review` avoids
a RuntimeWarning caused by __init__.py eagerly importing grippy.review
before the -m mechanism executes it as __main__.
"""

from grippy.review import main

if __name__ == "__main__":
    main()
