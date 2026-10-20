"""Ponto de entrada preservado; nenhuma integração na importação."""
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.cli import main
from src.monitor import DebouncedRunner, FileMonitor, file_hash, watch

if __name__ == "__main__":
    sys.exit(main(['watch', *sys.argv[1:]]))
