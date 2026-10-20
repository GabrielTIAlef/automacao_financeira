"""Renovação única por arquivo; uma rotação ambígua exige recuperação explícita."""
import json
from pathlib import Path
import time

from src.config import AutomationError
from src.storage import atomic_json, file_lock

TOKEN_URL = 'https://api-v2.contaazul.com/oauth/token'


class TokenStore:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock

    def access(self, http, client_id, client_secret):
        with file_lock(self.path.with_suffix(self.path.suffix + '.lock')):
            try:
                current = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(current, dict) or current.get('state', 'ready') != 'ready':
                    raise ValueError
                refresh = current['refresh_token']
                if not isinstance(refresh, str) or not refresh:
                    raise ValueError
                expires = current.get('expires_at', 0)
                if (not isinstance(expires, (int, float)) or isinstance(expires, bool)):
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError):
                raise AutomationError('Token indisponível ou recuperação necessária; valores omitidos.') from None
            access = current.get('access_token')
            if isinstance(access, str) and access and expires > self.clock() + 60:
                return access
            # Gravar ANTES do POST: queda de processo não deixa reutilizar refresh antigo cegamente.
            atomic_json(self.path, {**current, 'state': 'rotation_pending'})
            payload = http.request('POST', TOKEN_URL, safe=False,
                auth=(client_id, client_secret), data={'grant_type': 'refresh_token', 'refresh_token': refresh})
            if any(not isinstance(payload.get(k), str) or not payload[k] for k in ('access_token', 'refresh_token')):
                raise AutomationError('Resposta OAuth incompleta; recuperação do token necessária.')
            lifetime = payload.get('expires_in')
            if not isinstance(lifetime, int) or isinstance(lifetime, bool) or lifetime <= 60:
                raise AutomationError('Validade OAuth inválida; recuperação do token necessária.')
            atomic_json(self.path, {'state': 'ready', 'access_token': payload['access_token'],
                'refresh_token': payload['refresh_token'], 'expires_at': self.clock() + lifetime})
            return payload['access_token']
