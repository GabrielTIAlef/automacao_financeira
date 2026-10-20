from copy import deepcopy
from decimal import Decimal
import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from examples.fakes import Action, Driver, FakeSession, Response, Wait, sample, uid
from src.clients import ContaAzulClient, NotionClient, plain
from src.config import AutomationError, database_url
from src.contracts import day, identifier, money, transform
from src.http_client import HTTPClient, HTTPFailure
from src.monitor import DebouncedRunner, FileMonitor, watch
from src.oauth import TokenStore
from src.storage import atomic_json, file_lock
from src.automacao.RPA_Gestao_Financeira import profile_lock, run as refresh


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.guard = patch('requests.sessions.Session.request', side_effect=AssertionError('Rede real proibida'))
        self.guard.start()
        self.addCleanup(self.guard.stop)


class ContractTests(OfflineTest):
    def build(self, customers=None, receivables=None, pages=None):
        c, r, p = sample()
        return transform(c if customers is None else customers, r if receivables is None else receivables,
                         p if pages is None else pages, start='2026-01-01', reference='2026-01-31')

    def test_homonyms_preserved_by_uuid(self):
        result = self.build()
        self.assertEqual(len(result['customers']), 3)
        self.assertEqual(result['customers'][0]['nome'], result['customers'][1]['nome'])
        self.assertNotEqual(result['customers'][0]['cliente_id'], result['customers'][1]['cliente_id'])

    def test_exact_balance_and_document_zeroes(self):
        result = self.build()
        self.assertEqual(sum(r['nao_pago'] for r in result['receivables']), Decimal('130.00'))
        self.assertEqual(result['customers'][0]['documento'], '00000000000001')
        self.assertEqual([r['inadimplente'] for r in result['intents']], [True, True, False])

    def test_empty_overdue_is_valid_and_all_flags_false(self):
        result = self.build(receivables=[])
        self.assertEqual(result['receivables'], [])
        self.assertFalse(any(row['inadimplente'] for row in result['intents']))

    def test_empty_customer_base_rejected(self):
        with self.assertRaises(AutomationError):
            self.build(customers=[])

    def test_duplicate_customer_receivable_and_page_ids_rejected(self):
        for index in range(3):
            data = list(sample())
            data[index].append(deepcopy(data[index][0]))
            with self.subTest(index=index), self.assertRaises(AutomationError):
                self.build(*data)

    def test_missing_notion_mapping_and_unknown_customer_rejected(self):
        _, _, pages = sample()
        for mode in ('missing', 'unknown'):
            value = deepcopy(pages)
            if mode == 'missing':
                value[0].pop('cliente_id')
            else:
                value[0]['cliente_id'] = uid(999)
            with self.assertRaises(AutomationError):
                self.build(pages=value)

    def test_missing_customer_join_rejected(self):
        _, rows, _ = sample()
        rows[0]['cliente'] = {'id': uid(999)}
        with self.assertRaises(AutomationError):
            self.build(receivables=rows)

    def test_numeric_document_rejected(self):
        clients, _, _ = sample()
        clients[0]['documento'] = 123
        with self.assertRaises(AutomationError):
            self.build(customers=clients)

    def test_invalid_money_and_precision_never_coerced(self):
        for value in ('inválido', 'NaN', 'Infinity', '1.001', '10000000000000000', True, None, '1,2,3'):
            with self.subTest(kind=type(value).__name__), self.assertRaises(AutomationError):
                money(value)

    def test_brl_and_decimal_formats(self):
        self.assertEqual(money('R$ 1.234,56'), Decimal('1234.56'))
        self.assertEqual(money('1234.56'), Decimal('1234.56'))
        self.assertEqual(money('0.1') + money('0.2'), Decimal('0.30'))

    def test_dates_reject_ambiguous_invalid_and_numeric(self):
        for value in ('31/01/2026', '2026-02-30', 46000, None):
            with self.assertRaises(AutomationError):
                day(value)

    def test_window_and_financial_equation_rejected(self):
        for mode in ('window', 'sum', 'status'):
            _, rows, _ = sample()
            if mode == 'window': rows[0]['data_vencimento'] = '2026-02-01'
            if mode == 'sum': rows[0]['nao_pago'] = '1'
            if mode == 'status': rows[0]['status'] = 'RECEBIDO'
            with self.assertRaises(AutomationError):
                self.build(receivables=rows)

    def test_active_flag_must_be_boolean(self):
        clients, _, _ = sample()
        clients[0]['ativo'] = 'false'
        with self.assertRaises(AutomationError):
            self.build(customers=clients)


class HTTPTests(OfflineTest):
    def client(self, responses):
        session = Mock()
        session.request.side_effect = responses
        return HTTPClient(session=session, allow_live=True, sleep=lambda seconds: None), session

    def test_default_denies_network(self):
        with self.assertRaises(AutomationError):
            HTTPClient().request('GET', 'https://api.notion.com/v1/users/me', safe=True)

    def test_destination_and_redirect_blocked(self):
        client, session = self.client([Response({}, 302)])
        with self.assertRaises(AutomationError):
            client.request('GET', 'https://example.invalid')
        self.assertEqual(session.request.call_count, 0)
        with self.assertRaises(HTTPFailure):
            client.request('GET', 'https://api.notion.com/v1/users/me', safe=True)
        self.assertFalse(session.request.call_args.kwargs['allow_redirects'])

    def test_timeout_is_explicit_and_error_sanitized(self):
        client, session = self.client([requests.Timeout('sentinela confidencial')])
        with self.assertRaises(HTTPFailure) as raised:
            client.request('GET', 'https://api.notion.com/v1/users/me', safe=True)
        self.assertNotIn('sentinela', str(raised.exception))
        self.assertEqual(session.request.call_args.kwargs['timeout'], 30)

    def test_bounded_rate_limit_retries_for_reads(self):
        client, session = self.client([Response({}, 429)] * 3)
        with self.assertRaises(HTTPFailure):
            client.request('POST', 'https://api.notion.com/v1/data_sources/test/query', safe=True)
        self.assertEqual(session.request.call_count, 3)

    def test_writes_not_automatically_retried(self):
        for response in (Response({}, 429), Response({}, 500)):
            client, session = self.client([response])
            with self.assertRaises(HTTPFailure):
                client.request('POST', 'https://api.notion.com/v1/pages', safe=False)
            self.assertEqual(session.request.call_count, 1)

    def test_ambiguous_write_classification(self):
        client, _ = self.client([requests.Timeout('omitido')])
        with self.assertRaises(HTTPFailure) as raised:
            client.request('POST', 'https://api.notion.com/v1/pages', safe=False)
        self.assertTrue(raised.exception.ambiguous)

    def test_clients_paginate_documented_collections(self):
        session = FakeSession()
        client = ContaAzulClient(HTTPClient(session=session, allow_live=True), 'synthetic')
        self.assertEqual(len(client.customers()), 3)
        self.assertEqual(len(client.receivables('2026-01-01', '2026-01-31')), 2)

    def test_incomplete_empty_repeated_and_changing_pages_rejected(self):
        row = {'uuid': uid(1)}
        cases = [[{}], [{'items': [], 'totalItems': 1}],
                 [{'items': [row], 'totalItems': 2}] * 2,
                 [{'items': [row], 'totalItems': 2}, {'items': [], 'totalItems': 1}]]
        for values in cases:
            http = Mock()
            http.request.side_effect = values
            with self.assertRaises(AutomationError):
                ContaAzulClient(http, 'synthetic', max_pages=3).customers()

    def test_notion_repeated_cursor_and_missing_id_rejected(self):
        for responses in ([{'results': [], 'has_more': True, 'next_cursor': 'x'}] * 2,
                          [{'results': [{'id': uid(1), 'properties': {}}], 'has_more': False}]):
            http = Mock()
            http.request.side_effect = responses
            with self.assertRaises(AutomationError):
                NotionClient(http, 'synthetic', uid(900)).pages()

    def test_notion_update_does_not_write_manual_fields_or_title(self):
        http = Mock()
        client = NotionClient(http, 'synthetic', uid(900))
        client.apply({'cliente_id': uid(1), 'page_id': uid(101), 'nome': 'Nome', 'inadimplente': False})
        self.assertEqual(set(http.request.call_args.kwargs['json']['properties']), {'Inadimplente?'})

    def test_notion_create_contains_stable_id_and_data_source(self):
        http = Mock()
        NotionClient(http, 'synthetic', uid(900)).apply(
            {'cliente_id': uid(2), 'page_id': None, 'nome': 'Nome', 'inadimplente': True})
        body = http.request.call_args.kwargs['json']
        self.assertEqual(body['parent'], {'type': 'data_source_id', 'data_source_id': uid(900)})
        self.assertIn('Cliente_ID', body['properties'])


class OAuthTests(OfflineTest):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'token.json'
        atomic_json(self.path, {'refresh_token': 'synthetic_old', 'expires_at': 0})
        self.http = Mock()
        self.http.request.return_value = {'access_token': 'synthetic_access', 'refresh_token': 'synthetic_new', 'expires_in': 3600}

    def test_rotation_persists_both_tokens_and_expiry(self):
        access = TokenStore(self.path, clock=lambda: 100).access(self.http, 'synthetic', 'synthetic')
        data = json.loads(self.path.read_text())
        self.assertEqual(access, 'synthetic_access')
        self.assertEqual(data['refresh_token'], 'synthetic_new')
        self.assertEqual(data['expires_at'], 3700)
        self.assertEqual(self.http.request.call_args.kwargs['auth'], ('synthetic', 'synthetic'))

    def test_valid_cached_token_does_not_rotate(self):
        atomic_json(self.path, {'access_token': 'cached', 'refresh_token': 'synthetic', 'expires_at': 4000})
        self.assertEqual(TokenStore(self.path, clock=lambda: 100).access(self.http, 'x', 'y'), 'cached')
        self.http.request.assert_not_called()

    def test_ambiguous_rotation_blocks_reuse(self):
        self.http.request.side_effect = HTTPFailure(ambiguous=True)
        store = TokenStore(self.path)
        with self.assertRaises(HTTPFailure): store.access(self.http, 'x', 'y')
        with self.assertRaises(AutomationError): store.access(self.http, 'x', 'y')
        self.assertEqual(self.http.request.call_count, 1)

    def test_persistence_failure_after_rotation_leaves_recovery_marker(self):
        calls = [0]
        def fail_second(path, value):
            calls[0] += 1
            if calls[0] == 2: raise OSError('disk ficticio')
            return atomic_json(path, value)
        with patch('src.oauth.atomic_json', side_effect=fail_second), self.assertRaises(OSError):
            TokenStore(self.path).access(self.http, 'x', 'y')
        self.assertEqual(json.loads(self.path.read_text())['state'], 'rotation_pending')

    def test_invalid_payload_and_corrupted_file_fail_closed(self):
        self.http.request.return_value = {'access_token': 'synthetic'}
        with self.assertRaises(AutomationError): TokenStore(self.path).access(self.http, 'x', 'y')
        self.path.write_text('{invalid', encoding='utf-8')
        with self.assertRaises(AutomationError): TokenStore(self.path).access(self.http, 'x', 'y')

    def test_exclusive_lock_is_preserved_on_second_attempt(self):
        lock = self.path.with_suffix('.json.lock')
        with file_lock(lock):
            with self.assertRaises(AutomationError): TokenStore(self.path).access(self.http, 'x', 'y')
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())


class MonitorTests(OfflineTest):
    def test_no_overlap_and_change_during_run_is_replayed(self):
        entered, release = threading.Event(), threading.Event()
        active, peak, calls = [0], [0], [0]
        mutex = threading.Lock()
        def callback():
            with mutex:
                active[0] += 1; peak[0] = max(peak[0], active[0]); calls[0] += 1; count = calls[0]
            if count == 1:
                entered.set(); release.wait(3)
            with mutex: active[0] -= 1
        runner = DebouncedRunner(callback, debounce=0, cooldown=0)
        try:
            runner(); self.assertTrue(entered.wait(2)); runner(); runner(); release.set()
            self.assertTrue(runner.wait_idle())
            self.assertEqual(peak[0], 1)
            self.assertEqual(calls[0], 2)
        finally:
            release.set(); runner.close()

    def test_failure_retries_without_new_file_event(self):
        calls = [0]
        def callback():
            calls[0] += 1
            if calls[0] == 1: raise AutomationError('synthetic')
        runner = DebouncedRunner(callback, debounce=0, cooldown=0)
        try:
            runner(); self.assertTrue(runner.wait_idle()); self.assertEqual(calls[0], 2)
        finally: runner.close()

    def test_hashes_confirmed_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'file.xlsx'; file.write_bytes(b'old')
            callback = Mock()
            monitor = FileMonitor([file], callback, debounce=0, cooldown=0)
            old = dict(monitor.accepted)
            try:
                def verify(): self.assertEqual(monitor.accepted, old)
                callback.side_effect = verify
                file.write_bytes(b'new'); monitor.scan()
                self.assertTrue(monitor.runner.wait_idle())
                self.assertNotEqual(monitor.accepted, old)
                callback.assert_called_once()
            finally: monitor.close()

    def test_polling_recovers_initialization_and_later_observer_failure(self):
        for fail_at_start in (True, False):
            with self.subTest(fail_at_start=fail_at_start), tempfile.TemporaryDirectory() as directory:
                file = Path(directory) / 'manual.xlsx'; file.write_bytes(b'old')
                stop = threading.Event()
                class DeadObserver:
                    def schedule(self, *args, **kwargs): pass
                    def start(self):
                        file.write_bytes(b'new')
                        if fail_at_start: raise RuntimeError('synthetic')
                    def is_alive(self): return False
                    def stop(self): pass
                    def join(self, **kwargs): pass
                timer = threading.Timer(3, stop.set); timer.start()
                calls = []
                try:
                    watch([file], lambda: (calls.append(1), stop.set()), stop=stop, interval=.01,
                          debounce=0, cooldown=0, observer_factory=DeadObserver)
                    self.assertEqual(calls, [1])
                finally: timer.cancel()


class BrowserConfigurationTests(OfflineTest):
    def test_refresh_default_denied(self):
        with self.assertRaises(AutomationError): refresh()

    def test_fake_browser_confirms_request_not_completion(self):
        driver = Driver()
        with tempfile.TemporaryDirectory() as directory:
            result = refresh(allow_live=True, dataset='DEMO', directory=directory, profile='Default',
                driver_factory=lambda options: driver, wait_factory=Wait, action_factory=Action)
        self.assertTrue(driver.block.button.clicked)
        self.assertTrue(driver.closed)
        self.assertEqual(result, {'status': 'requested', 'completion_verified': False})

    def test_missing_dataset_or_timeout_propagated_and_browser_closed(self):
        for timeout in (True, False):
            driver = Driver(name='OUTRO')
            factory = Mock(side_effect=RuntimeError('sensitive')) if timeout else Wait
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(AutomationError):
                refresh(allow_live=True, dataset='DEMO', directory=directory, profile='Default',
                    driver_factory=lambda options: driver, wait_factory=factory, action_factory=Action)
            self.assertTrue(driver.closed)

    def test_existing_chrome_locks_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'SingletonLock'; marker.write_text('synthetic')
            with self.assertRaises(AutomationError):
                with profile_lock(directory): pass
            self.assertTrue(marker.exists())

    def test_all_entrypoints_import_without_external_effects(self):
        with patch('selenium.webdriver.Chrome', side_effect=AssertionError('browser')), \
                patch('subprocess.run', side_effect=AssertionError('process')):
            for module in ('src.cli', 'src.extracao.ContaAzul', 'src.transformacao.inadimplencia',
                           'src.automacao.observador_excel', 'src.automacao.RPA_Gestao_Financeira'):
                importlib.reload(importlib.import_module(module))

    def test_cli_requires_explicit_live_flag(self):
        from src.cli import main
        for command in ('collect', 'sync', 'refresh', 'watch'):
            with patch('src.cli.create_engine', side_effect=AssertionError('database')), self.assertLogs(level='ERROR'):
                self.assertEqual(main([command]), 1)

    @patch('src.config.load_dotenv')
    def test_missing_database_config_fails_without_defaults(self, _):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(AutomationError):
            database_url()


if __name__ == '__main__':
    unittest.main()
