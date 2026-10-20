"""Fluxo fictício até PostgreSQL local, Notion fake e navegador fake."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from examples.fakes import Action, Driver, FakeSession, Wait, uid
from src.clients import ContaAzulClient, NotionClient
from src.database import initialize
from src.http_client import HTTPClient
from src.pipeline import run
from src.sync import dispatch
from src.automacao.RPA_Gestao_Financeira import run as refresh


def main():
    engine = None
    try:
        url = make_url(os.getenv('AUTO_DEMO_DATABASE_URL', ''))
        if (url.drivername != 'postgresql+psycopg2' or url.query
                or url.host not in ('localhost', '127.0.0.1', '::1') or not url.database
                or not (url.database == 'automacao_demo' or url.database.startswith('automacao_demo_'))):
            raise ValueError('Destino da demo inválido.')
        with patch('requests.sessions.Session.request', side_effect=AssertionError('HTTP real proibido na demo')):
            engine = create_engine(url, connect_args={'connect_timeout': 10})
            initialize(engine)
            session = FakeSession()
            http = HTTPClient(session=session, allow_live=True)
            notion = NotionClient(http, 'synthetic', uid(900))
            result = run(engine, ContaAzulClient(http, 'synthetic'), notion,
                         start='2026-01-01', reference='2026-01-31', directory=ROOT / 'data/demo')
            result['notion_fake'] = dispatch(engine, notion)
            with tempfile.TemporaryDirectory(prefix='auto_profile_') as directory:
                result['powerbi_fake'] = refresh(allow_live=True, dataset='DEMO', directory=directory,
                    profile='Default', driver_factory=lambda options: Driver(), wait_factory=Wait, action_factory=Action)
            print(json.dumps(result))
        return 0
    except Exception:
        print('Demonstração interrompida; consulte configuração local. Valores omitidos.', file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    sys.exit(main())
