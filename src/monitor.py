"""Worker único, eventos coalescidos e hashes confirmados só após sucesso."""
import hashlib
import logging
from pathlib import Path
import threading
import time

from src.config import AutomationError

LOG = logging.getLogger(__name__)


def file_hash(path):
    try:
        with Path(path).open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


class DebouncedRunner:
    def __init__(self, fn, debounce=10, cooldown=60):
        if debounce < 0 or cooldown < 0:
            raise AutomationError('Intervalos do observador inválidos.')
        self.fn, self.debounce, self.cooldown = fn, debounce, cooldown
        self.condition = threading.Condition()
        self.version = self.completed = 0
        self.changed = self.finished = float('-inf')
        self.running, self.stopping, self.errors = False, False, 0
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def __call__(self):
        with self.condition:
            if self.stopping:
                return
            self.version += 1
            self.changed = time.monotonic()
            self.condition.notify_all()

    def _loop(self):
        while True:
            with self.condition:
                while not self.stopping:
                    if self.version <= self.completed:
                        self.condition.wait()
                        continue
                    wait = max(self.changed + self.debounce, self.finished + self.cooldown) - time.monotonic()
                    if wait > 0:
                        self.condition.wait(wait)
                        continue
                    version = self.version
                    self.running = True
                    break
                if self.stopping:
                    return
            success = False
            try:
                self.fn()
                success = True
            except Exception:
                LOG.warning('Automação falhou; mudança permanece pendente, sem detalhes sensíveis.')
            with self.condition:
                self.running = False
                self.finished = time.monotonic()
                if success:
                    self.completed = version
                else:
                    self.errors += 1
                    # Mesmo cooldown zero recebe intervalo mínimo de retry para não girar em loop.
                    self.finished += max(0, 0.05 - self.cooldown)
                self.condition.notify_all()

    def wait_idle(self, timeout=5):
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.running or self.version > self.completed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
        return True

    def close(self, timeout=120):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        self.worker.join(timeout)
        if self.worker.is_alive():
            raise AutomationError('Automação ainda ativa; encerramento não confirmado.')


class FileMonitor:
    def __init__(self, files, callback, *, debounce=10, cooldown=60):
        self.files = tuple(Path(p).resolve() for p in files)
        if not self.files or len(set(self.files)) != len(self.files):
            raise AutomationError('Configure arquivos distintos para monitorar.')
        self.lock = threading.Lock()
        self.observed = {p: file_hash(p) for p in self.files}
        self.accepted = dict(self.observed)
        self.callback = callback
        self.runner = DebouncedRunner(self._run, debounce, cooldown)

    def scan(self):
        current = {p: file_hash(p) for p in self.files}
        with self.lock:
            changed = current != self.observed
            self.observed = current
        if changed:
            self.runner()

    def _run(self):
        with self.lock:
            snapshot = dict(self.observed)
        if any(value is None or file_hash(path) != value for path, value in snapshot.items()):
            raise AutomationError('Arquivo ausente, ilegível ou em alteração; refresh adiado.')
        self.callback()
        with self.lock:
            self.accepted = snapshot
        self.scan()  # Mudanças ocorridas durante a execução não são perdidas.

    def close(self):
        self.runner.close()


def watch(files, callback, *, stop=None, interval=30, debounce=10, cooldown=60, observer_factory=None):
    if interval <= 0:
        raise AutomationError('Intervalo de polling inválido.')
    stop = stop or threading.Event()
    monitor = FileMonitor(files, callback, debounce=debounce, cooldown=cooldown)
    observer = None
    try:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
            class Handler(FileSystemEventHandler):
                def on_any_event(self, event):
                    if event.event_type in ('modified', 'created', 'moved', 'deleted'):
                        monitor.scan()
            observer = (observer_factory or Observer)()
            directories = {p.parent for p in monitor.files if p.parent.is_dir()}
            if not directories:
                raise AutomationError('Nenhuma pasta disponível para observação.')
            for directory in directories:
                observer.schedule(Handler(), str(directory), recursive=False)
            observer.start()
        except Exception:
            if observer is not None:
                observer.stop()
                if observer.is_alive():
                    observer.join(timeout=5)
            observer = None
            LOG.warning('Watchdog indisponível; polling ativo.')
        while not stop.wait(interval):
            if observer is not None and not observer.is_alive():
                observer.stop()
                observer.join(timeout=5)
                observer = None
                LOG.warning('Watchdog interrompido; polling mantém monitoramento.')
            monitor.scan()  # Polling de segurança também enquanto Watchdog está vivo.
    except KeyboardInterrupt:
        stop.set()
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)
        monitor.close()
