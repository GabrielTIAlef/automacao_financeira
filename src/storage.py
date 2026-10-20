"""Arquivos atômicos e locks exclusivos; nenhum lock alheio é removido."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

from src.config import AutomationError


@contextmanager
def file_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise AutomationError('Recurso reservado por outra execução; não remova locks ativos.') from None
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def prepare_file(target, writer):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix='.' + target.stem + '-', suffix=target.suffix, dir=target.parent)
    os.close(descriptor)
    temporary = Path(filename)
    try:
        writer(temporary)
        return temporary, target
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_json(target, value):
    def writer(path):
        with path.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    temporary, target = prepare_file(target, writer)
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
