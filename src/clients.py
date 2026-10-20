"""Adaptadores com contratos explícitos. Nenhuma rede na importação."""
from src.config import AutomationError
from src.contracts import day, identifier

CA_BASE = 'https://api-v2.contaazul.com/v1'
NOTION_BASE = 'https://api.notion.com/v1'
NOTION_VERSION = '2025-09-03'
MANUAL_FIELDS = ('Status', 'Probabilidade recuperação', 'Ciente do Débito?', 'Tem negociação comercial?',
                 '1º Contato de Cobrança?', 'Negociação Realizada?', 'Situação da Dívida')


class ContaAzulClient:
    def __init__(self, http, access_token, *, max_pages=1000):
        self.http, self.headers, self.max_pages = http, {'Authorization': 'Bearer ' + access_token}, max_pages

    def _pages(self, path, params, *, collection='itens', total_field='itens_totais'):
        result, fingerprints = [], set()
        expected_total = None
        for page in range(1, self.max_pages + 1):
            payload = self.http.request('GET', CA_BASE + path, safe=True, headers=self.headers,
                                        params={**params, 'pagina': page, 'tamanho_pagina': 100})
            items = payload.get(collection)
            total = payload.get(total_field)
            if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                raise AutomationError('Conta Azul: contrato de paginação inválido.')
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                raise AutomationError('Conta Azul: contagem total ausente ou inválida.')
            if expected_total is not None and total != expected_total:
                raise AutomationError('Conta Azul: total mudou durante a paginação; tente uma nova coleta.')
            expected_total = total
            if not items:
                if len(result) != expected_total:
                    raise AutomationError('Conta Azul: páginas não reconciliam com total anunciado.')
                return result
            ids = tuple(str(row.get('id', row.get('uuid', ''))) for row in items)
            if ids in fingerprints:
                raise AutomationError('Conta Azul: página repetida.')
            fingerprints.add(ids)
            result.extend(items)
        raise AutomationError('Conta Azul: limite de páginas atingido sem comprovar conclusão.')

    def customers(self):
        # Contrato atual documentado, distinto do /pessoa legado do código original.
        rows = self._pages('/pessoas', {'tipo_perfil': 'Cliente'}, collection='items', total_field='totalItems')
        result = []
        for row in rows:
            key = row.get('uuid', row.get('id'))
            if 'uuid' in row and 'id' in row and identifier(row['uuid']) != identifier(row['id']):
                raise AutomationError('Conta Azul: identidades de cliente conflitantes.')
            result.append({**row, 'uuid': identifier(key)})
        return result

    def receivables(self, start, reference):
        start, reference = day(start), day(reference)
        return self._pages('/financeiro/eventos-financeiros/contas-a-receber/buscar',
            {'data_vencimento_de': start.isoformat(), 'data_vencimento_ate': reference.isoformat(), 'status': 'ATRASADO'})


def plain(prop):
    if not isinstance(prop, dict):
        raise AutomationError('Notion: propriedade obrigatória ausente.')
    kind = prop.get('type')
    if kind in ('title', 'rich_text'):
        values = prop.get(kind)
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise AutomationError('Notion: texto inválido.')
        pieces = []
        for value in values:
            piece = value.get('plain_text', value.get('text', {}).get('content'))
            if not isinstance(piece, str):
                raise AutomationError('Notion: texto incompleto.')
            pieces.append(piece)
        return ''.join(pieces)
    if kind in ('select', 'status'):
        value = prop.get(kind)
        if value is None:
            return None
        if isinstance(value, dict) and isinstance(value.get('name'), str):
            return value['name']
    if kind == 'checkbox' and isinstance(prop.get('checkbox'), bool):
        return prop['checkbox']
    raise AutomationError('Notion: tipo de propriedade não suportado; não ignorado silenciosamente.')


class NotionClient:
    def __init__(self, http, token, data_source_id, *, title='Nome', max_pages=1000):
        self.http, self.source_id, self.title, self.max_pages = http, identifier(data_source_id), title, max_pages
        self.headers = {'Authorization': 'Bearer ' + token, 'Notion-Version': NOTION_VERSION}

    def pages(self):
        result, seen = [], set()
        cursor = None
        for _ in range(self.max_pages):
            body = {'page_size': 100}
            if cursor:
                body['start_cursor'] = cursor
            payload = self.http.request('POST', NOTION_BASE + '/data_sources/' + self.source_id + '/query',
                                        safe=True, headers=self.headers, json=body)
            entries = payload.get('results')
            if (not isinstance(entries, list) or not isinstance(payload.get('has_more'), bool)
                    or payload.get('request_status', {}).get('type', 'complete') != 'complete'):
                raise AutomationError('Notion: consulta incompleta ou contrato inválido.')
            for page in entries:
                try:
                    props = page['properties']
                    result.append({'page_id': identifier(page['id']),
                        'cliente_id': identifier(plain(props['Cliente_ID'])),
                        'fields': {name: plain(props[name]) for name in MANUAL_FIELDS if name in props}})
                except (KeyError, TypeError):
                    raise AutomationError('Notion: mapeamento Cliente_ID obrigatório.') from None
            if not payload['has_more']:
                return result
            cursor = payload.get('next_cursor')
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise AutomationError('Notion: cursor ausente ou repetido.')
            seen.add(cursor)
        raise AutomationError('Notion: limite de paginação atingido.')

    def apply(self, intent):
        props = {'Inadimplente?': {'rich_text': [{'text': {'content': 'Sim' if intent['inadimplente'] else 'Não'}}]}}
        if intent['page_id']:
            # Não sobrescrever título ou propriedades manuais de uma página existente.
            return self.http.request('PATCH', NOTION_BASE + '/pages/' + identifier(intent['page_id']),
                                      safe=False, headers=self.headers, json={'properties': props})
        props.update({self.title: {'title': [{'text': {'content': intent['nome']}}]},
                      'Cliente_ID': {'rich_text': [{'text': {'content': identifier(intent['cliente_id'])}}]}})
        return self.http.request('POST', NOTION_BASE + '/pages', safe=False, headers=self.headers,
            json={'parent': {'type': 'data_source_id', 'data_source_id': self.source_id}, 'properties': props})
