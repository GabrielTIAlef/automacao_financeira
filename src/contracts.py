"""Contrato da amostra: UUIDs estáveis e inadimplência na janela consultada."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from uuid import UUID

from src.config import AutomationError


def identifier(value):
    if not isinstance(value, str):
        raise AutomationError('ID deve ser UUID textual.')
    try:
        return str(UUID(value))
    except ValueError:
        raise AutomationError('ID deve ser UUID textual válido.') from None


def string(value, *, nullable=False):
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise AutomationError('Texto obrigatório inválido.')
    if any(ord(c) < 32 for c in value):
        raise AutomationError('Texto contém caracteres de controle.')
    return value.strip()


def money(value):
    if value is None or isinstance(value, bool):
        raise AutomationError('Valor monetário obrigatório inválido.')
    try:
        source = str(value).strip()
        if source.startswith('R$'):
            source = source[2:].strip()
        if ',' in source:
            if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:\.\d{3})+),\d{2}', source):
                raise ValueError
            source = source.replace('.', '').replace(',', '.')
        elif not re.fullmatch(r'-?\d+(?:\.\d+)?', source):
            raise ValueError
        number = Decimal(source)
        if not number.is_finite() or number != number.quantize(Decimal('.01')) or abs(number) >= 10**16:
            raise ValueError
        return number.quantize(Decimal('.01'))
    except (ValueError, InvalidOperation):
        raise AutomationError('Valor monetário fora do contrato; arredondamento não é automático.') from None


def day(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise AutomationError('Data inválida; use AAAA-MM-DD.') from None


def transform(customers, receivables, pages, *, start, reference):
    start, reference = day(start), day(reference)
    if start > reference:
        raise AutomationError('Janela de consulta inválida.')
    if not isinstance(customers, list) or not customers or not isinstance(receivables, list) or not isinstance(pages, list):
        raise AutomationError('Coleções incompletas ou cadastro vazio.')
    clients, debts, manual = {}, {}, {}
    try:
        for row in customers:
            client_id = identifier(row['uuid'])
            if client_id in clients or not isinstance(row['ativo'], bool):
                raise AutomationError('Cliente duplicado ou flag ativo inválida.')
            document = row.get('documento')
            if document is not None and (not isinstance(document, str) or len(document) > 30):
                raise AutomationError('Documento deve permanecer texto.')
            clients[client_id] = {'cliente_id': client_id, 'nome': string(row['nome']),
                                  'documento': document, 'ativo': row['ativo']}
        for row in receivables:
            receivable_id = identifier(row['id'])
            nested = row['cliente']
            client_id = identifier(nested['id'] if isinstance(nested, dict) else nested)
            due = day(row['data_vencimento'])
            if receivable_id in debts or client_id not in clients or not start <= due <= reference or row['status'] != 'ATRASADO':
                raise AutomationError('Recebível duplicado, sem cliente ou fora da cobertura.')
            if 'total' in row and 'valor_total' in row and money(row['total']) != money(row['valor_total']):
                raise AutomationError('Campos de total conflitantes.')
            total, paid, unpaid = money(row.get('valor_total', row.get('total'))), money(row['pago']), money(row['nao_pago'])
            if min(total, paid, unpaid) < 0 or total != paid + unpaid:
                raise AutomationError('Recebível não reconcilia total, pago e saldo.')
            debts[receivable_id] = {'recebivel_id': receivable_id, 'cliente_id': client_id, 'status': 'ATRASADO',
                'total': total, 'pago': paid, 'nao_pago': unpaid, 'vencimento': due,
                'descricao': string(row.get('descricao'), nullable=True), 'dias_atraso': (reference - due).days}
        page_ids = set()
        for row in pages:
            client_id, page_id = identifier(row['cliente_id']), identifier(row['page_id'])
            if client_id not in clients or client_id in manual or page_id in page_ids:
                raise AutomationError('Mapeamento Notion ausente, duplicado ou fora do cadastro.')
            fields = row.get('fields', {})
            if not isinstance(fields, dict) or any(not isinstance(k, str) or (v is not None and not isinstance(v, (str, bool))) for k, v in fields.items()):
                raise AutomationError('Campos manuais fora do contrato.')
            manual[client_id] = {'cliente_id': client_id, 'page_id': page_id, 'fields': fields}
            page_ids.add(page_id)
    except (KeyError, TypeError, AttributeError):
        raise AutomationError('Resposta de origem incompleta; publicação bloqueada.') from None
    overdue = {row['cliente_id'] for row in debts.values() if row['nao_pago'] > 0}
    intents = [{'cliente_id': key, 'nome': row['nome'], 'inadimplente': key in overdue,
                'page_id': manual.get(key, {}).get('page_id')}
               for key, row in sorted(clients.items())]
    return {'customers': list(clients.values()), 'receivables': list(debts.values()),
            'manual': list(manual.values()), 'intents': intents, 'start': start, 'reference': reference}
