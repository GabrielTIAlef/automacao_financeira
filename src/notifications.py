"""Notificações opcionais com mensagens fechadas, sem dados, caminhos ou traceback."""
import logging
import os

import requests

EVENTS = {'refresh_requested': 'Solicitação de atualização enviada; conclusão não verificada.',
          'refresh_failed': 'Falha na solicitação de atualização; consulte os logs locais sanitizados.'}


def notify(event, *, allow_live=False, session=None):
    if event not in EVENTS:
        raise ValueError('Evento de notificação não permitido.')
    url = os.getenv('SLACK_WEBHOOK_URL', '')
    if not allow_live or not url:
        return False
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'hooks.slack.com':
        raise ValueError('Webhook fora do destino permitido.')
    try:
        response = (session or requests).post(url, json={'text': EVENTS[event]}, timeout=10, allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise requests.RequestException
        return True
    except requests.RequestException:
        logging.warning('Notificação não entregue; detalhes omitidos.')
        return False
