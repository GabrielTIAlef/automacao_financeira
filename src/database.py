"""Uma transação para snapshots e intenções; nenhum efeito externo é transacional."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import uuid

from sqlalchemy import inspect, text

from src.config import AutomationError, ROOT

LOCK_ID = 724193830
DDL = ROOT / 'sql/001_schema.sql'


def ddl_hash():
    return sha256(DDL.read_text(encoding='utf-8').encode()).hexdigest()


@contextmanager
def locked(engine):
    if engine.dialect.name != 'postgresql':
        raise AutomationError('Esta carga requer PostgreSQL.')
    with engine.connect() as conn:
        acquired = conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK_ID}).scalar_one()
        conn.commit()
        if not acquired:
            raise AutomationError('Outra execução financeira está em andamento.')
        try:
            yield conn
        finally:
            if conn.in_transaction():
                conn.rollback()
            conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_ID})
            conn.commit()


def check_schema(conn):
    try:
        row = conn.execute(text('SELECT version, ddl_sha256 FROM af.schema_version')).one()
        if row.version != 1 or row.ddl_sha256 != ddl_hash():
            raise AutomationError('Schema incompatível; migração explícita necessária.')
    except AutomationError:
        raise
    except Exception:
        raise AutomationError('Schema ausente ou incompatível; use --init apenas em banco novo.') from None


def initialize(engine):
    try:
        with locked(engine) as conn, conn.begin():
            inspector = inspect(conn)
            if inspector.has_table('schema_version', schema='af'):
                check_schema(conn)
                return
            if 'af' in inspector.get_schema_names() and (
                    inspector.get_table_names(schema='af') or inspector.get_view_names(schema='af')):
                raise AutomationError('Schema af contém objetos legados; nenhuma migração automática.')
            for statement in DDL.read_text(encoding='utf-8').split(';'):
                if statement.strip():
                    conn.execute(text(statement))
            conn.execute(text('INSERT INTO af.schema_version VALUES (1,:hash)'), {'hash': ddl_hash()})
    except AutomationError:
        raise
    except Exception:
        raise AutomationError('Inicialização falhou; alterações revertidas.') from None


def reconcile(conn, bundle, run_id):
    for table, expected in (('clientes', len(bundle['customers'])), ('"Conta_Azul"', len(bundle['receivables'])),
                            ('"Conta_Azul_Mao"', len(bundle['manual'])), ('outbox_notion', len(bundle['intents']))):
        count = conn.execute(text(f'SELECT count(*) FROM af.{table} WHERE run_id=:id'), {'id': run_id}).scalar_one()
        if count != expected:
            raise AutomationError('Reconciliação de contagem falhou.')
    sums = conn.execute(text('SELECT COALESCE(sum(total),0),COALESCE(sum(pago),0),COALESCE(sum(nao_pago),0) '
                              'FROM af."Conta_Azul"')).one()
    for index, key in enumerate(('total', 'pago', 'nao_pago')):
        if sums[index] != sum((r[key] for r in bundle['receivables']), Decimal('0')):
            raise AutomationError('Reconciliação financeira falhou.')


def publish(conn, bundle):
    """Chamada pelo orquestrador sob locked(); bundle já passou pelo contrato."""
    run_id = str(uuid.uuid4())
    counts = {key: len(bundle[key]) for key in ('customers', 'receivables', 'manual', 'intents')}
    balance = sum((row['nao_pago'] for row in bundle['receivables']), Decimal('0.00'))
    with conn.begin():
        conn.execute(text("SET LOCAL lock_timeout='10s'"))
        check_schema(conn)
        conn.execute(text('INSERT INTO af.execucoes VALUES (:run,:now,:start,:ref,CAST(:counts AS jsonb),:balance,:source)'),
                     {'run': run_id, 'now': datetime.now(timezone.utc), 'start': bundle['start'],
                      'ref': bundle['reference'], 'counts': json.dumps(counts), 'balance': balance,
                      'source': bundle['notion_source_id']})
        conn.execute(text('UPDATE af.clientes SET presente=false'))
        conn.execute(text('INSERT INTO af.clientes VALUES (:cliente_id,:nome,:documento,:ativo,true,:run_id) '
                          'ON CONFLICT(cliente_id) DO UPDATE SET nome=EXCLUDED.nome,documento=EXCLUDED.documento,'
                          'ativo=EXCLUDED.ativo,presente=true,run_id=EXCLUDED.run_id'),
                     [{**row, 'run_id': run_id} for row in bundle['customers']])
        conn.execute(text('DELETE FROM af."Conta_Azul_Mao"'))
        conn.execute(text('DELETE FROM af."Conta_Azul"'))
        if bundle['receivables']:
            conn.execute(text('INSERT INTO af."Conta_Azul" VALUES (:recebivel_id,:cliente_id,:status,:total,:pago,'
                              ':nao_pago,:vencimento,:descricao,:dias_atraso,:run_id)'),
                         [{**row, 'run_id': run_id} for row in bundle['receivables']])
        if bundle['manual']:
            conn.execute(text('INSERT INTO af."Conta_Azul_Mao" VALUES (:cliente_id,:page_id,CAST(:fields AS jsonb),:run_id)'),
                         [{**row, 'fields': json.dumps(row['fields']), 'run_id': run_id} for row in bundle['manual']])
        # Intenções antigas pendentes não podem sobrescrever um snapshot mais recente.
        conn.execute(text("UPDATE af.outbox_notion SET state='superseded' WHERE state IN ('pending','blocked')"))
        conn.execute(text('INSERT INTO af.outbox_notion(intent_id,run_id,cliente_id,nome,inadimplente,page_id,state) '
                          "VALUES (:intent_id,:run_id,:cliente_id,:nome,:inadimplente,:page_id,'pending')"),
                     [{**row, 'intent_id': str(uuid.uuid4()), 'run_id': run_id} for row in bundle['intents']])
        reconcile(conn, bundle, run_id)
    return {'run_id': run_id, 'database_committed': True, 'rows': counts, 'saldo': str(balance)}


def outbox_status(conn):
    rows = conn.execute(text('SELECT state,count(*) FROM af.outbox_notion GROUP BY state')).all()
    conn.commit()
    return dict(rows)
