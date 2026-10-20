"""Entrega serializada; uma criação ambígua nunca é repetida cegamente."""
from sqlalchemy import text

from src.config import AutomationError
from src.contracts import identifier
from src.database import check_schema, locked
from src.http_client import HTTPFailure


def dispatch(engine, notion):
    with locked(engine) as conn:
        with conn.begin():
            check_schema(conn)
            targets = conn.execute(text("SELECT DISTINCT e.notion_source_id FROM af.outbox_notion o "
                "JOIN af.execucoes e USING(run_id) WHERE o.state IN ('pending','inflight','ambiguous','blocked')")).scalars().all()
            if any(str(value) != notion.source_id for value in targets):
                raise AutomationError('Destino Notion diverge do lote; nenhuma entrega enviada.')
        mapping, pages_seen = {}, set()
        for row in notion.pages():
            client_id, page_id = identifier(row['cliente_id']), identifier(row['page_id'])
            if client_id in mapping or page_id in pages_seen:
                raise AutomationError('Notion ambíguo; nenhuma escrita enviada.')
            mapping[client_id] = page_id
            pages_seen.add(page_id)
        with conn.begin():
            pending = [dict(r) for r in conn.execute(text("SELECT * FROM af.outbox_notion WHERE state='pending' ORDER BY intent_id")).mappings()]
        counts = {'complete': 0, 'blocked': 0, 'ambiguous': 0}
        for row in pending:
            client_id = str(row['cliente_id'])
            page_id = mapping.get(client_id)
            with conn.begin():
                unresolved = conn.execute(text("SELECT count(*) FROM af.outbox_notion WHERE cliente_id=:client "
                    "AND state IN ('inflight','ambiguous') AND page_id IS NULL"), {'client': client_id}).scalar_one()
                if (unresolved and not page_id) or (row['page_id'] and not page_id):
                    conn.execute(text("UPDATE af.outbox_notion SET state='blocked',reason='mapping_reconciliation_required' WHERE intent_id=:id"), {'id': row['intent_id']})
                    counts['blocked'] += 1
                    continue
                conn.execute(text("UPDATE af.outbox_notion SET state='inflight',page_id=:page WHERE intent_id=:id"),
                             {'id': row['intent_id'], 'page': page_id})
            intent = {**row, 'cliente_id': client_id, 'page_id': page_id}
            try:
                response = notion.apply(intent)
                returned_id = identifier(response['id'])
                if page_id and returned_id != page_id:
                    raise AutomationError('Resposta de escrita não reconciliável.')
                mapping[client_id] = returned_id
                state, reason = 'complete', None
            except HTTPFailure as error:
                state = 'ambiguous' if error.ambiguous else 'blocked'
                reason = 'external_response_uncertain' if error.ambiguous else 'external_request_rejected'
            except Exception:
                state, reason = 'ambiguous', 'external_response_uncertain'
            with conn.begin():
                conn.execute(text('UPDATE af.outbox_notion SET state=:state,reason=:reason,page_id=:page WHERE intent_id=:id'),
                             {'state': state, 'reason': reason, 'page': mapping.get(client_id, page_id), 'id': row['intent_id']})
                if state == 'complete':
                    conn.execute(text("UPDATE af.outbox_notion SET state='superseded',reason='reconciled_by_stable_id',page_id=:page "
                        "WHERE cliente_id=:client AND intent_id<>:id AND state IN ('inflight','ambiguous')"),
                        {'page': mapping[client_id], 'client': client_id, 'id': row['intent_id']})
            counts[state] += 1
        with conn.begin():
            remaining = conn.execute(text("SELECT count(*) FROM af.outbox_notion WHERE state IN ('pending','blocked','ambiguous','inflight')")).scalar_one()
        return {'status': 'complete' if remaining == 0 else 'incomplete', 'unresolved': remaining, **counts}
