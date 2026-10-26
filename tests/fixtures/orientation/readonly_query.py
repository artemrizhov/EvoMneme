"""Audited single-statement SQL launcher for disposable synthetic probe data only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme import Executor


def run(database, sql_file, params, max_rows, max_output_bytes, audit):
    database = Path(database).resolve(strict=True)
    area = (ROOT / '.evomneme-tests').resolve()
    if not database.is_relative_to(area):
        raise ValueError('Only excluded synthetic test databases are permitted')
    receipt = json.loads((database.parent / 'receipt.json').read_text(encoding='utf-8'))
    if receipt.get('synthetic_fixture') is not True or Path(receipt['database']).resolve() != database:
        raise ValueError('A matching synthetic fixture receipt is required')
    audit = Path(audit).resolve()
    if (not audit.is_relative_to(database.parent) or audit == database
            or audit.name == 'receipt.json' or (audit.exists() and audit.samefile(database))):
        raise ValueError('Audit output must be a separate file in the fixture directory')
    request = dict(sql=Path(sql_file).read_text(encoding='utf-8'), params=params,
                   max_rows=max_rows, max_output_bytes=max_output_bytes)
    # Establish audit access before opening the executor or executing any SQL.
    audit.parent.mkdir(parents=True, exist_ok=True)
    with audit.open('a', encoding='utf-8') as stream:
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        executor = Executor(database, history=False)
        try:
            executor.connection.execute('PRAGMA query_only=ON')
            result = executor.execute_sql(**request)
        finally:
            executor.close()
        after = hashlib.sha256(database.read_bytes()).hexdigest()
        record = dict(request=request, result=result,
                      result_bytes=len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')),
                      database_sha256_before=before, database_sha256_after=after, database_unchanged=before == after)
        stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
    if before != after:
        raise RuntimeError('Synthetic database bytes changed; inspect the audit')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--sql-file', required=True, type=Path)
    parser.add_argument('--params', required=True, type=json.loads)
    parser.add_argument('--max-rows', type=int, default=12)
    parser.add_argument('--max-output-bytes', type=int, default=8192)
    parser.add_argument('--audit', required=True, type=Path)
    arguments = vars(parser.parse_args())
    result = run(**arguments)
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    raise SystemExit(0 if result['ok'] else 1)
