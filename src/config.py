import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]


class AutomationError(RuntimeError):
    """Mensagem operacional sem valores sensíveis."""


def required(name):
    load_dotenv(ROOT / '.env', override=False)
    value = os.getenv(name, '').strip()
    if not value:
        raise AutomationError(f'Configure {name}; consulte .env.example.')
    return value


def configured_path(name, default=None):
    load_dotenv(ROOT / '.env', override=False)
    value = os.getenv(name, default)
    if not value:
        raise AutomationError(f'Configure {name}.')
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def database_url():
    values = {key: required('POSTGRES_' + key.upper()) for key in ('host', 'user', 'password', 'db')}
    try:
        port = int(os.getenv('POSTGRES_PORT', '5432'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise AutomationError('POSTGRES_PORT inválida.') from None
    return URL.create('postgresql+psycopg2', host=values['host'], port=port,
                      username=values['user'], password=values['password'], database=values['db'])
