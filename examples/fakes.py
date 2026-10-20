from copy import deepcopy
from uuid import UUID


def uid(number):
    return str(UUID(int=number))


def sample():
    customers = [{'uuid': uid(n), 'nome': 'Cliente Fictício' if n < 3 else 'Outro Cliente Fictício',
                  'documento': f'{n:014d}', 'ativo': True} for n in (1, 2, 3)]
    receivables = [
        {'id': uid(11), 'cliente': {'id': uid(1)}, 'status': 'ATRASADO', 'valor_total': '100.10',
         'pago': '20.10', 'nao_pago': '80.00', 'data_vencimento': '2026-01-10', 'descricao': 'Parcela fictícia A'},
        {'id': uid(12), 'cliente': {'id': uid(2)}, 'status': 'ATRASADO', 'valor_total': '50.00',
         'pago': '0.00', 'nao_pago': '50.00', 'data_vencimento': '2026-01-15', 'descricao': 'Parcela fictícia B'},
    ]
    pages = [{'page_id': uid(101), 'cliente_id': uid(1), 'fields': {'Status': 'Em negociação', 'Ciente do Débito?': True}}]
    return deepcopy(customers), deepcopy(receivables), deepcopy(pages)


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}

    def json(self):
        return deepcopy(self.payload)


def rich(value, kind='rich_text'):
    return {'type': kind, kind: [{'plain_text': value, 'text': {'content': value}}]}


class FakeSession:
    """Emula os formatos documentados. Não usa sockets nem requests."""
    def __init__(self):
        self.customers, self.receivables, self.pages = sample()
        self.writes = []

    def request(self, method, url, **kwargs):
        if method == 'GET' and url.endswith('/pessoas'):
            page = kwargs['params']['pagina']
            return Response({'items': self.customers[(page-1)*2:page*2], 'totalItems': len(self.customers)})
        if method == 'GET' and url.endswith('/contas-a-receber/buscar'):
            page = kwargs['params']['pagina']
            return Response({'itens': self.receivables if page == 1 else [], 'itens_totais': len(self.receivables)})
        if method == 'POST' and url.endswith('/query'):
            entries = []
            for page in self.pages:
                props = {'Cliente_ID': rich(page['cliente_id'])}
                props.update({name: {'type': 'checkbox', 'checkbox': value} if isinstance(value, bool)
                              else rich(value) for name, value in page['fields'].items()})
                entries.append({'id': page['page_id'], 'properties': props})
            return Response({'results': entries, 'has_more': False, 'next_cursor': None})
        if method == 'POST' and url.endswith('/pages'):
            body = kwargs['json']
            client_id = body['properties']['Cliente_ID']['rich_text'][0]['text']['content']
            if any(row['cliente_id'] == client_id for row in self.pages):
                raise AssertionError('Criação duplicada na simulação.')
            page = {'cliente_id': client_id, 'page_id': uid(200 + len(self.pages)), 'fields': {}}
            self.pages.append(page)
            self.writes.append(('create', client_id))
            return Response({'id': page['page_id']})
        if method == 'PATCH' and '/pages/' in url:
            page_id = url.rsplit('/', 1)[1]
            assert set(kwargs['json']['properties']) == {'Inadimplente?'}
            page = next(p for p in self.pages if p['page_id'] == page_id)
            self.writes.append(('update', page['cliente_id']))
            return Response({'id': page_id})
        raise AssertionError('Requisição inesperada na simulação.')


class Button:
    def __init__(self):
        self.clicked = False
    def click(self):
        self.clicked = True


class Block:
    def __init__(self, name):
        self.name, self.button = name, Button()
    def find_element(self, *args):
        return self
    def get_attribute(self, name):
        return self.name


class Driver:
    def __init__(self, name='DEMO'):
        self.block, self.closed = Block(name), False
    def get(self, url):
        self.url = url
    def find_elements(self, *args):
        return [self.block]
    def quit(self):
        self.closed = True


class Wait:
    def __init__(self, target, timeout):
        self.target = target
    def until(self, condition):
        return self.target.button if isinstance(self.target, Block) else True


class Action:
    def __init__(self, driver):
        pass
    def move_to_element(self, element):
        return self
    def perform(self):
        pass
