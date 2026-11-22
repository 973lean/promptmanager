# Double-click to open Prompt Manager (runs without a console window).
import os, runpy, sys

pm = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pm.py")
sys.argv = [pm] + sys.argv[1:]
runpy.run_path(pm, run_name="__main__")
