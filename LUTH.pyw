#!/usr/bin/env pythonw
"""
LUTH — Silent launcher (no console window on Windows).
Double-click this file to start LUTH GUI.
"""
import os
import sys

# Ensure we run from the correct directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import main
main()
