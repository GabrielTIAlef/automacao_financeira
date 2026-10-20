from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from examples.fakes import FakeSession, sample, uid
from src.clients import ContaAzulClient, NotionClient
from src.config import AutomationError, ROOT
from src import database
from src.http_client import HTTPClient, HTTPFailure
from src.pipeline import run
from src.sync import dispatch

ADMIN = os.getenv('AUTO_TEST_PG_ADMIN_URL')
ISOLATED = os.getenv('AUTO_TEST_PG_ISOLATED') == '1'


@unittest.skipUnless(ADMIN and ISOLATED, 'PostgreSQL isolado não iniciado; use scripts/validate_postgres.py')
class PostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(ADMIN)
        if (url.drivername != 'postgresql+psycopg2' or url.query or url.database != 'postgres'
                or url.host not in ('localhost', '127.0.0.1', '::1') or url.username != 'auto_test'):
            raise RuntimeError('Exige PostgreSQL local explícito auto_test.')
        cls.url = url
        cls.admin = create_engine(url, poolclass=NullPool, isolation_level='AUTOCOMMIT',
                                  connect_args={'connect_timeout': 10})

    @classmethod
    def tearDownClass(cls):
        cls.admin.dispose()

    def setUp(self):
        self.guard = patch('requests.sessions.Session.request', side_effect=AssertionError('Rede real proibida'))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.name = 'auto_test_' + uuid.uuid4().hex
        with self.admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{self.name}"'))
        self.engine = create_engine(self.url.set(database=self.name), connect_args={'connect_timeout': 10})
        database.initialize(self.engine)
        self.directory = tempfile.TemporaryDirectory(prefix='auto_pg_test_')
        self.output = Path(self.directory.name)
        self.session = FakeSession()
        http = HTTPClient(session=self.session, allow_live=True)
        self.conta, self.notion = ContaAzulClient(http, 'synthetic'), NotionClient(http, 'synthetic', uid(900))

    def tearDown(self):
        self.engine.dispose()
        assert self.name.startswith('auto_test_') and len(self.name) == 42
        with self.admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{self.name}" WITH (FORCE)'))
        path = self.output.resolve()
        assert path.parent == Path(tempfile.gettempdir()).resolve() and path.name.startswith('auto_pg_test_')
        self.directory.cleanup()

    def scalar(self, sql):
        with self.engine.connect() as conn:
            return conn.execute(text(sql)).scalar_one()

    def sql(self, sql):
        with self.engine.begin() as conn:
            conn.execute(text(sql))

    def execute(self):
        return run(self.engine, self.conta, self.notion, start='2026-01-01',
                   reference='2026-01-31', directory=self.output)

    def snapshot(self):
        with self.engine.connect() as conn:
            return {table: conn.execute(text(f'SELECT * FROM af.{table} ORDER BY 1')).all()
                    for table in ('clientes', '"Conta_Azul"', '"Conta_Azul_Mao"', 'execucoes', 'outbox_notion')}

    def artifacts(self):
        return {p.name: p.read_bytes() for p in self.output.iterdir() if p.is_file()}

    def test_end_to_end_fake_http_to_database_and_files(self):
        result = self.execute()
        self.assertTrue(result['database_committed'])
        self.assertEqual(result['saldo'], '130.00')
        self.assertEqual(self.scalar('SELECT count(*) FROM af."Conta_Azul"'), 2)
        self.assertEqual(self.scalar('SELECT count(*) FROM af.clientes WHERE presente'), 3)
        self.assertEqual(self.scalar('SELECT count(*) FROM af.outbox_notion'), 3)
        self.assertEqual(self.session.writes, [])
        self.assertTrue((self.output/'inadimplencia.xlsx').exists())

    def test_homonyms_and_document_zeroes_survive_database(self):
        self.execute()
        self.assertEqual(self.scalar("SELECT count(*) FROM af.clientes WHERE nome='Cliente Fictício'"), 2)
        self.assertEqual(self.scalar(f"SELECT documento FROM af.clientes WHERE cliente_id='{uid(1)}'"), '00000000000001')

    def test_repeat_has_stable_tables_and_supersedes_only_pending_intents(self):
        self.execute()
        oid = self.scalar("SELECT 'af.\"Conta_Azul\"'::regclass::oid")
        self.execute()
        self.assertEqual(self.scalar('SELECT count(*) FROM af."Conta_Azul"'), 2)
        self.assertEqual(self.scalar("SELECT 'af.\"Conta_Azul\"'::regclass::oid"), oid)
        self.assertEqual(self.scalar("SELECT count(*) FROM af.outbox_notion WHERE state='pending'"), 3)
        self.assertEqual(self.scalar("SELECT count(*) FROM af.outbox_notion WHERE state='superseded'"), 3)

    def test_zero_overdue_clears_snapshot_and_queues_false_flags(self):
        self.execute()
        self.session.receivables = []
        result = self.execute()
        self.assertEqual(result['saldo'], '0.00')
        self.assertEqual(self.scalar('SELECT count(*) FROM af."Conta_Azul"'), 0)
        self.assertEqual(self.scalar('SELECT count(*) FROM af.inadimplencia_por_cliente WHERE inadimplente'), 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM af.outbox_notion WHERE state='pending' AND inadimplente"), 0)

    def test_partial_extraction_preserves_database_files_and_intents(self):
        self.execute()
        before, files = self.snapshot(), self.artifacts()
        with patch.object(self.conta, 'receivables', side_effect=HTTPFailure(status=500)), self.assertRaises(AutomationError):
            self.execute()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(files, self.artifacts())

    def test_contract_failure_preserves_previous_snapshot(self):
        self.execute()
        before = self.snapshot()
        self.session.receivables[0]['nao_pago'] = 'inválido'
        with self.assertRaises(AutomationError): self.execute()
        self.assertEqual(before, self.snapshot())

    def test_sql_failure_after_snapshot_delete_rolls_back_everything(self):
        self.execute()
        self.sql("CREATE FUNCTION af.reject() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic'; END $$")
        self.sql('CREATE TRIGGER reject BEFORE INSERT ON af."Conta_Azul" FOR EACH ROW EXECUTE FUNCTION af.reject()')
        before, files = self.snapshot(), self.artifacts()
        with self.assertRaises(AutomationError) as raised: self.execute()
        self.assertIn('banco_confirmado=False', str(raised.exception))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(files, self.artifacts())
        self.sql('DROP TRIGGER reject ON af."Conta_Azul"')
        self.execute()  # Lock liberado após falha.

    def test_reconciliation_failure_rolls_back_ledger_and_outbox(self):
        with patch('src.database.reconcile', side_effect=AutomationError('synthetic')), self.assertRaises(AutomationError):
            self.execute()
        for table in ('clientes', '"Conta_Azul"', 'execucoes', 'outbox_notion'):
            self.assertEqual(self.scalar(f'SELECT count(*) FROM af.{table}'), 0)

    def test_files_prepared_before_database_write(self):
        with patch('src.pipeline.prepare_file', side_effect=OSError('synthetic')), self.assertRaises(AutomationError):
            self.execute()
        self.assertEqual(self.scalar('SELECT count(*) FROM af.execucoes'), 0)

    def test_file_failure_after_commit_reports_committed_database(self):
        with patch('src.pipeline.os.replace', side_effect=OSError('synthetic')), self.assertRaises(AutomationError) as raised:
            self.execute()
        self.assertIn('banco_confirmado=True', str(raised.exception))
        self.assertEqual(self.scalar('SELECT count(*) FROM af.execucoes'), 1)
        self.assertFalse((self.output/'latest_run.json').exists())

    def test_concurrent_execution_rejected_without_overlap(self):
        with database.locked(self.engine):
            with self.assertRaises(AutomationError): self.execute()
            with self.assertRaises(AutomationError): dispatch(self.engine, self.notion)
        self.execute()

    def test_schema_initialization_repeatable_and_mismatch_rejected(self):
        self.execute()
        before = self.snapshot()
        database.initialize(self.engine)
        self.assertEqual(before, self.snapshot())
        self.sql("UPDATE af.schema_version SET ddl_sha256=repeat('0',64)")
        with self.assertRaises(AutomationError): self.execute()
        self.assertEqual(before, self.snapshot())

    def test_constraints_enforce_fk_uniqueness_and_reconciliation(self):
        self.execute()
        for statement in (
            f"UPDATE af.\"Conta_Azul\" SET cliente_id='{uid(999)}'",
            'UPDATE af."Conta_Azul" SET total=0',
            f"UPDATE af.\"Conta_Azul_Mao\" SET cliente_id='{uid(999)}'",
        ):
            with self.assertRaises(IntegrityError): self.sql(statement)
        self.assertEqual(self.scalar('SELECT sum(nao_pago) FROM af."Conta_Azul"'), Decimal('130.00'))

    def test_dispatch_updates_by_id_and_preserves_manual_fields(self):
        self.execute()
        manual = deepcopy(self.session.pages[0]['fields'])
        result = dispatch(self.engine, self.notion)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['complete'], 3)
        self.assertEqual(self.session.pages[0]['fields'], manual)
        self.assertEqual(len(self.session.pages), 3)

    def test_successful_dispatch_not_sent_again(self):
        self.execute(); dispatch(self.engine, self.notion)
        before = len(self.session.writes)
        self.assertEqual(dispatch(self.engine, self.notion)['complete'], 0)
        self.assertEqual(len(self.session.writes), before)

    def test_ambiguous_create_without_returned_page_is_not_repeated(self):
        self.execute()
        original = self.notion.apply
        def fail_create(intent):
            if intent['cliente_id'] == uid(2): raise HTTPFailure(ambiguous=True)
            return original(intent)
        with patch.object(self.notion, 'apply', side_effect=fail_create):
            first = dispatch(self.engine, self.notion)
        self.assertEqual(first['ambiguous'], 1)
        self.execute()  # Outra coleta não autoriza repetir criação sem provar página existente.
        second = dispatch(self.engine, self.notion)
        self.assertEqual(second['blocked'], 1)
        self.assertEqual(second['status'], 'incomplete')
        self.assertNotIn(('create', uid(2)), self.session.writes)

    def test_remote_create_then_timeout_reconciles_by_id_before_update(self):
        self.execute()
        original = self.notion.apply
        def create_then_timeout(intent):
            result = original(intent)
            if intent['cliente_id'] == uid(2): raise HTTPFailure(ambiguous=True)
            return result
        with patch.object(self.notion, 'apply', side_effect=create_then_timeout):
            self.assertEqual(dispatch(self.engine, self.notion)['ambiguous'], 1)
        self.execute()
        self.assertEqual(dispatch(self.engine, self.notion)['status'], 'complete')
        self.assertEqual(self.session.writes.count(('create', uid(2))), 1)
        self.assertIn(('update', uid(2)), self.session.writes)

    def test_inflight_crash_blocks_new_creation_until_mapping_known(self):
        self.execute()
        self.sql(f"UPDATE af.outbox_notion SET state='inflight' WHERE cliente_id='{uid(2)}'")
        self.execute()
        result = dispatch(self.engine, self.notion)
        self.assertEqual(result['blocked'], 1)
        self.assertNotIn(('create', uid(2)), self.session.writes)

    def test_ambiguous_mapping_blocks_all_external_writes(self):
        self.execute()
        self.session.pages.append(deepcopy(self.session.pages[0]))
        with self.assertRaises(AutomationError): dispatch(self.engine, self.notion)
        self.assertEqual(self.session.writes, [])

    def test_missing_known_page_not_recreated(self):
        self.execute()
        self.session.pages = []
        result = dispatch(self.engine, self.notion)
        self.assertEqual(result['blocked'], 1)
        self.assertNotIn(('create', uid(1)), self.session.writes)

    def test_hard_rejection_remains_incomplete_without_blind_retry(self):
        self.execute()
        with patch.object(self.notion, 'apply', side_effect=HTTPFailure(status=403)):
            self.assertEqual(dispatch(self.engine, self.notion)['blocked'], 3)
        self.assertEqual(dispatch(self.engine, self.notion)['status'], 'incomplete')
        self.assertEqual(self.session.writes, [])

    def test_sync_read_failure_does_not_mark_intents_inflight(self):
        self.execute()
        with patch.object(self.notion, 'pages', side_effect=HTTPFailure(status=500)), self.assertRaises(HTTPFailure):
            dispatch(self.engine, self.notion)
        self.assertEqual(self.scalar("SELECT count(*) FROM af.outbox_notion WHERE state='pending'"), 3)

    def test_changed_data_source_does_not_redirect_queued_intents(self):
        self.execute()
        self.notion.source_id = uid(901)
        with patch.object(self.notion, 'pages', side_effect=AssertionError('Consulta externa')), self.assertRaises(AutomationError):
            dispatch(self.engine, self.notion)
        self.assertEqual(self.session.writes, [])

    def test_demo_cli_is_fully_offline_except_local_database(self):
        # Banco isolado criado exclusivamente para a demo desta suíte.
        name = 'automacao_demo_' + uuid.uuid4().hex
        with self.admin.connect() as conn: conn.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            env = {k: v for k, v in os.environ.items() if not k.startswith(('POSTGRES_', 'AUTO_', 'NOTION_', 'SLACK_', 'CHROME_', 'CONTA_AZUL_'))}
            env['AUTO_DEMO_DATABASE_URL'] = self.url.set(database=name).render_as_string(hide_password=False)
            process = subprocess.run([sys.executable, '-X', 'utf8', 'scripts/run_demo.py'], cwd=ROOT,
                                      env=env, capture_output=True, timeout=90)
            self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
            result = json.loads(process.stdout)
            self.assertEqual(result['saldo'], '130.00')
            self.assertEqual(result['notion_fake']['status'], 'complete')
            self.assertFalse(result['powerbi_fake']['completion_verified'])
        finally:
            assert name.startswith('automacao_demo_') and len(name) == 47
            with self.admin.connect() as conn: conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


if __name__ == '__main__':
    unittest.main()
