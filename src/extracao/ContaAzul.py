"""Ponto de entrada preservado; nenhuma integração na importação."""
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.cli import main

if __name__ == "__main__":
    sys.exit(main(['collect', *sys.argv[1:]]))
