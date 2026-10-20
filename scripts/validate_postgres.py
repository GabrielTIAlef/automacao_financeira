"""Cria cluster PostgreSQL descartável em loopback e executa a suíte, sem serviço Windows."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path,
                        help="Diretório contendo initdb, pg_ctl e postgres.")
    parser.add_argument("--demo", action="store_true", help="Gerar também os arquivos da demonstração fictícia.")
    args = parser.parse_args()
    suffix = ".exe" if os.name == "nt" else ""
    binaries = args.pg_bin.resolve()
    for name in ("initdb", "pg_ctl", "postgres"):
        if not (binaries / (name + suffix)).is_file():
            raise SystemExit("Executáveis PostgreSQL não encontrados.")
    storage = ROOT / ".local-test"
    storage.mkdir(exist_ok=True)
    cluster = Path(tempfile.mkdtemp(prefix="automacao_pg_", dir=storage)).resolve()
    if not cluster.is_relative_to(storage.resolve()):
        raise SystemExit("Diretório de teste fora do local esperado.")
    data, log = cluster / "data", cluster / "postgres.log"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    def command(name, *values):
        output = cluster / (name + "-command.log")
        # Pipes herdados por postgres.exe podem manter communicate() bloqueado no Windows.
        with output.open("wb") as stream:
            result = subprocess.run([str(binaries / (name + suffix)), *map(str, values)],
                                    stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=creationflags, timeout=120)
        if result.returncode:
            # Somente cluster fictício; logs preservados localmente para diagnóstico.
            raise RuntimeError(f"Falha em {name}; consulte os logs em {cluster.name}.")
        return output.read_text(encoding="utf-8", errors="replace").strip()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    started = False
    try:
        command("initdb", "-D", data, "-U", "auto_test", "--auth=trust", "--encoding=UTF8", "--locale=C")
        started = True
        command("pg_ctl", "-D", data, "-l", log, "-o", f"-h 127.0.0.1 -p {port}", "-w", "start")
        version = command("postgres", "--version")
        env = os.environ.copy()
        # Credenciais corporativas não são consultadas por esta suíte.
        for key in list(env):
            if key.startswith(("POSTGRES_", "FINANCE_", "AUTO_", "CONTA_AZUL_", "NOTION_", "SLACK_", "CHROME_", "POWERBI_", "GESTTA_")):
                env.pop(key, None)
        env["AUTO_TEST_PG_ADMIN_URL"] = f"postgresql+psycopg2://auto_test@127.0.0.1:{port}/postgres"
        env["AUTO_TEST_PG_ISOLATED"] = "1"
        test_log = cluster / "tests.log"
        result_path = cluster / "tests_result.json"
        with test_log.open("wb") as stream:
            result = subprocess.run([sys.executable, "-X", "utf8", "scripts/run_tests.py",
                                     "--require-postgresql", "--result-path", str(result_path)],
                                    cwd=ROOT, env=env, creationflags=creationflags,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        summary = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
        metadata = {"postgres": version, "loopback_only": True, "port": port,
                    "tests_exit_code": result.returncode, "cluster_stopped": False,
                    "tests": summary}
        exit_code = result.returncode
        if args.demo and exit_code == 0:
            import psycopg2
            connection = psycopg2.connect(host="127.0.0.1", port=port, user="auto_test", dbname="postgres")
            try:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute("CREATE DATABASE automacao_demo")
            finally:
                connection.close()
            env["AUTO_DEMO_DATABASE_URL"] = f"postgresql+psycopg2://auto_test@127.0.0.1:{port}/automacao_demo"
            demo_log = cluster / "demo.log"
            with demo_log.open("wb") as stream:
                demo = subprocess.run([sys.executable, "-X", "utf8", "scripts/run_demo.py"],
                                      cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                      creationflags=creationflags, timeout=120)
            metadata["demo_exit_code"] = demo.returncode
            exit_code = demo.returncode
            if demo.returncode == 0:
                demo_result = json.loads(demo_log.read_text(encoding="utf-8"))
                metadata["demo"] = {"status": demo_result["status"], "rows": demo_result["rows"]}
        print("\n".join(test_log.read_text(encoding="utf-8", errors="replace").splitlines()[-18:]), flush=True)
    finally:
        if started:
            command("pg_ctl", "-D", data, "-m", "fast", "-w", "stop")
    if started:
        metadata["cluster_stopped"] = True
        (storage / "last_validation.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(json.dumps(metadata))
        return exit_code


if __name__ == "__main__":
    sys.exit(main())
