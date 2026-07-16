"""python -m equipmap 으로 웹 버전을 실행."""

import sys

if __name__ == "__main__":
    if "--desktop" in sys.argv:
        from equipmap.app import run
    else:
        from equipmap.web import run

    run()
