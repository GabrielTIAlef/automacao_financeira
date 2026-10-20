"""HTTP explícito, com timeout e retries limitados somente em operações seguras."""
import time
from urllib.parse import urlsplit

import requests

from src.config import AutomationError


class HTTPFailure(AutomationError):
    def __init__(self, *, status=None, ambiguous=False):
        super().__init__(f'Falha HTTP{(" " + str(status)) if status else ""}; conteúdo omitido.')
        self.status, self.ambiguous = status, ambiguous


class HTTPClient:
    def __init__(self, *, session=None, allow_live=False, timeout=30, retries=2, sleep=time.sleep):
        if timeout <= 0 or not 0 <= retries <= 5:
            raise AutomationError('Limites HTTP inválidos.')
        self.session = session or requests.Session()
        self.allow_live, self.timeout, self.retries, self.sleep = allow_live, timeout, retries, sleep

    def request(self, method, url, *, safe=False, **kwargs):
        if not self.allow_live:
            raise AutomationError('Rede desativada; execução real precisa ser explicitamente autorizada.')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in (
                'api-v2.contaazul.com', 'api.notion.com', 'hooks.slack.com') or parsed.username or parsed.password:
            raise AutomationError('Destino HTTP fora da lista permitida.')
        # Não aceitar redirecionamentos para outro host junto de credenciais.
        for attempt in range(self.retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, allow_redirects=False, **kwargs)
            except requests.RequestException:
                raise HTTPFailure(ambiguous=not safe) from None
            status = response.status_code
            if status == 429 and safe and attempt < self.retries:
                try:
                    delay = min(max(float(response.headers.get('Retry-After', '1')), 0), 10)
                except (ValueError, TypeError):
                    delay = 1
                self.sleep(delay)
                continue
            if not 200 <= status < 300:
                raise HTTPFailure(status=status, ambiguous=not safe and status >= 500)
            try:
                payload = response.json()
            except (ValueError, TypeError):
                raise HTTPFailure(ambiguous=not safe) from None
            if not isinstance(payload, dict):
                raise HTTPFailure(ambiguous=not safe)
            return payload
        raise HTTPFailure(status=429)
