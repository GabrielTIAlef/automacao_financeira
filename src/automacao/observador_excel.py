#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import os
import sys
import time
import threading
import hashlib
import traceback
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from RPA_Gestao_Financeira import run as run_rpa, send_slack

FILES = [
    r"G:\Drives compartilhados\1. Departamentos - Análise de Dados\PBI - Gestão Financeira\Dados\Gestão de Restituições.xlsx",
    r"G:\Drives compartilhados\1. Departamentos - Análise de Dados\PBI - Gestão Financeira\Dados\Conta_azul.xlsm",
]
DEBOUNCE_SECONDS  = 10   
COOLDOWN_SECONDS  = 60   
POLL_INTERVAL     = 30  
USE_POLLING_FALLBACK = True

def norm(p):
    return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))

def file_hash(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024*1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def _quote_arg(a: str) -> str:
    a = str(a)
    if not a:
        return '""'
    if any(c in a for c in ' \t"'):
        return '"' + a.replace('"', r'\"') + '"'
    return a

class DebouncedRunner:
    def __init__(self, fn, debounce, cooldown):
        self.fn = fn
        self.debounce = debounce
        self.cooldown = cooldown
        self.timer = None
        self.lock = threading.Lock()
        self.last_run_ts = 0.0

    def __call__(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.debounce, self._maybe_run)
            self.timer.daemon = True
            self.timer.start()

    def _maybe_run(self):
        with self.lock:
            now = time.time()
            if now - self.last_run_ts < self.cooldown:
                self.timer = threading.Timer(self.cooldown - (now - self.last_run_ts), self._maybe_run)
                self.timer.daemon = True
                self.timer.start()
                return
            self.last_run_ts = now
        try:
            send_slack("Atualização detectada")
            self.fn()
            send_slack("Atualização Power BI ")
        except Exception as e:
            send_slack(f"Falha: {e}\n{traceback.format_exc()}")

class MultiFileHandler(FileSystemEventHandler):
    def __init__(self, files_list, hashes_dict, callback):
        super().__init__()
        self.files_list  = files_list
        self.hashes_dict = hashes_dict
        self.callback    = callback

    def on_modified(self, event): self._scan_all(reason=f"modified: {event.src_path}")
    def on_created (self, event): self._scan_all(reason=f"created: {event.src_path}")
    def on_moved   (self, event): self._scan_all(reason=f"moved: {getattr(event, 'src_path', '?')} -> {getattr(event, 'dest_path', '?')}")

    def _scan_all(self, reason=""):
        changed_any = False
        changed_list = []
        for p in self.files_list:
            if os.path.isfile(p):
                new_hash = file_hash(p)
                old_hash = self.hashes_dict.get(p)
                if new_hash and new_hash != old_hash:
                    self.hashes_dict[p] = new_hash
                    changed_any = True
                    changed_list.append(p)
        if changed_any:
            try:
                base_names = [os.path.basename(x) for x in changed_list]
                send_slack("Mudança detectada:" + ", ".join(base_names))
            except Exception:
                pass
            self.callback()

def start_watchdog(files):
    files = [norm(p) for p in files]
    dirs = sorted({ os.path.dirname(p) for p in files })

    ok_dirs, bad_dirs = [], []
    for d in dirs:
        if os.path.isdir(d):
            ok_dirs.append(d)
        else:
            bad_dirs.append(d)
    for d in bad_dirs:
        msg = f"Pasta inexistente: {d}"
        print("AVISO", msg)
        try:
            send_slack(msg)
        except Exception:
            pass

    hashes = {}
    for p in files:
        h = file_hash(p)
        hashes[p] = h
        if h is None:
            aviso = f"Arquivo ausente: {os.path.basename(p)}"
            print("AVISO", aviso)
            try:
                send_slack(aviso)
            except Exception:
                pass

    handler = MultiFileHandler(files, hashes, DebouncedRunner(run_rpa, DEBOUNCE_SECONDS, COOLDOWN_SECONDS))
    observer = Observer()

    if not ok_dirs:
        return None, [], hashes, handler

    for d in ok_dirs:
        try:
            observer.schedule(handler, path=d, recursive=False)
        except FileNotFoundError:
            erro = f"Não conseguiu observar {d}"
            print("ERRO", erro)
            try:
                send_slack(erro)
            except Exception:
                pass

    if getattr(observer, "_emitters", None):
        observer.start()
        try:
            send_slack("watchdog iniciado para:\n• " + "\n• ".join(ok_dirs))
        except Exception:
            pass
        print("INFO observando:", ok_dirs)
        return observer, ok_dirs, hashes, handler
    else:
        return None, [], hashes, handler

def start_polling(files, hashes, handler):
    files = [norm(p) for p in files]
    def loop():
        try:
            send_slack("Polling iniciado")
        except Exception:
            pass
        print("INFO Polling fallback ativo")
        while True:
            time.sleep(POLL_INTERVAL)
            for p in files:
                if os.path.isfile(p):
                    new_hash = file_hash(p)
                    old_hash = hashes.get(p)
                    if new_hash and new_hash != old_hash:
                        hashes[p] = new_hash
                        try:
                            send_slack("Mudança em: " + os.path.basename(p))
                        except Exception:
                            pass
                        handler.callback()
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t

def main():
    files = [norm(p) for p in FILES]
    print("Arquivos monitorados")
    for p in files:
        print(" -", p, "| existe?", os.path.isfile(p))

    observer, dirs, hashes, handler = start_watchdog(files)

    # Se watchdog não iniciou e fallback habilitado -> polling
    if not observer and USE_POLLING_FALLBACK:
        start_polling(files, hashes, handler)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    # Watchdog ativo
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if observer:
            observer.stop()
            observer.join()

if __name__ == "__main__":
    main()

