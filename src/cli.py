"""Operações explícitas. Nenhuma integração real é padrão da demonstração."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine

from src.clients import ContaAzulClient, NotionClient
from src.config import AutomationError, configured_path, database_url, required
from src.contracts import day
from src.database import initialize
from src.http_client import HTTPClient
from src.oauth import TokenStore
from src.pipeline import run
from src.sync import dispatch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'collect', 'sync', 'refresh', 'watch'))
    parser.add_argument('--allow-live', action='store_true', help='Permitir explicitamente integrações da conta autorizada.')
    parser.add_argument('--start', help='Início da janela em AAAA-MM-DD, obrigatório em collect.')
    parser.add_argument('--reference', help='Data de referência AAAA-MM-DD, obrigatória em collect.')
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.command != 'init' and not args.allow_live:
            raise AutomationError('Operação externa desativada; use a demo fictícia ou autorize --allow-live.')
        if args.command in ('refresh', 'watch'):
            from src.automacao.RPA_Gestao_Financeira import run as refresh
            from src.notifications import notify
            # Carrega configuração antes de ler a lista do observador.
            required('POWERBI_DATASET_NAME')
            def callback():
                result = refresh(allow_live=True)
                notify('refresh_requested', allow_live=True)
                return result
            if args.command == 'watch':
                from src.monitor import watch
                paths = [configured_path('WATCH_FILE_1'), configured_path('WATCH_FILE_2')]
                watch(paths, callback, interval=float(os.getenv('WATCH_POLL_INTERVAL', '30')),
                      debounce=float(os.getenv('WATCH_DEBOUNCE_SECONDS', '10')),
                      cooldown=float(os.getenv('WATCH_COOLDOWN_SECONDS', '60')))
                return 0
            print(json.dumps(callback()))
            return 0
        start = reference = None
        if args.command == 'collect':
            start, reference = day(args.start), day(args.reference)
        engine = create_engine(database_url(), connect_args={'connect_timeout': 10}, pool_pre_ping=True)
        if args.command == 'init':
            initialize(engine)
            print(json.dumps({'status': 'schema_ready'}))
            return 0
        http = HTTPClient(allow_live=True)
        notion = NotionClient(http, required('NOTION_TOKEN'), required('NOTION_DATA_SOURCE_ID'),
                              title=required('NOTION_TITLE_PROPERTY'))
        if args.command == 'sync':
            result = dispatch(engine, notion)
            print(json.dumps(result))
            return 0 if result['status'] == 'complete' else 1
        access = TokenStore(configured_path('CONTA_AZUL_TOKEN_PATH')).access(http,
                            required('CONTA_AZUL_CLIENT_ID'), required('CONTA_AZUL_CLIENT_SECRET'))
        result = run(engine, ContaAzulClient(http, access), notion, start=start,
                     reference=reference, directory=configured_path('DATA_DIR', 'data'))
        print(json.dumps(result))
        return 0
    except AutomationError as error:
        logging.error('%s', error)
        return 1
    except Exception:
        logging.error('Operação interrompida; valores e detalhes externos omitidos.')
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    sys.exit(main())
