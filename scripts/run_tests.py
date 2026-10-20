"""Executa a suíte e rejeita validação completa com PostgreSQL omitido."""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-postgresql', action='store_true')
    parser.add_argument('--result-path', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    missing = args.require_postgresql and (os.getenv('AUTO_TEST_PG_ISOLATED') != '1' or bool(result.skipped))
    summary = {'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
               'skipped': len(result.skipped), 'postgresql_required': args.require_postgresql,
               'successful': result.wasSuccessful() and not missing and result.testsRun > 0}
    if args.result_path:
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary))
    return 0 if summary['successful'] else 1


if __name__ == '__main__':
    sys.exit(main())
