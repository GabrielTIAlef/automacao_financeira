"""Coordena a publicação local; Notion e Power BI são comandos separados."""
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path

import pandas as pd

from src.config import AutomationError
from src.contracts import identifier, transform
from src.database import locked, publish
from src.storage import prepare_file

RECEIVABLE_COLUMNS = ('recebivel_id', 'cliente_id', 'status', 'total', 'pago', 'nao_pago',
                      'vencimento', 'descricao', 'dias_atraso')


def excel_value(value):
    if isinstance(value, Decimal):
        return str(value)  # Excel não preserva 18 dígitos como número.
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def run(engine, conta, notion, *, start, reference, directory):
    files = []
    committed, phase = False, 'lock'
    try:
        with locked(engine) as conn:
            phase = 'extração'
            customers = conta.customers()
            receivables = conta.receivables(start, reference)
            pages = notion.pages()
            phase = 'validação'
            bundle = transform(customers, receivables, pages, start=start, reference=reference)
            bundle['notion_source_id'] = identifier(notion.source_id)
            phase = 'preparação de arquivos'
            directory = Path(directory)
            target = directory / 'inadimplencia.xlsx'
            def workbook(path):
                with pd.ExcelWriter(path, engine='openpyxl') as writer:
                    for name, rows, cols in (
                            ('Recebiveis', bundle['receivables'], RECEIVABLE_COLUMNS),
                            ('Clientes', bundle['customers'], ('cliente_id', 'nome', 'documento', 'ativo')),
                            ('Controle_Manual', bundle['manual'], ('cliente_id', 'page_id', 'fields'))):
                        frame = pd.DataFrame(rows, columns=cols).map(excel_value)
                        frame.to_excel(writer, sheet_name=name, index=False)
            files.append(prepare_file(target, workbook))
            phase = 'publicação PostgreSQL'
            result = publish(conn, bundle)
            committed = True
            result.update({'status': 'local_complete', 'notion': 'queued_not_sent',
                           'powerbi': 'not_requested', 'excel_sha256': sha256(files[0][0].read_bytes()).hexdigest()})
            files.append(prepare_file(directory / 'latest_run.json',
                lambda p: p.write_text(json.dumps(result, indent=2), encoding='utf-8')))
            phase = 'publicação de arquivos'
            for temporary, destination in files:
                os.replace(temporary, destination)
            return result
    except Exception:
        raise AutomationError(f'Fluxo interrompido em {phase}; banco_confirmado={committed}. Valores omitidos.') from None
    finally:
        for temporary, _ in files:
            temporary.unlink(missing_ok=True)
