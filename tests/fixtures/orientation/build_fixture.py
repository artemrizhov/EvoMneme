"""Build disposable synthetic orientation data, never a host knowledge store."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = Path(__file__).with_name('sources')


def build(output):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Fixture output must be empty: ' + str(output))
    output.mkdir(parents=True, exist_ok=True)
    source_root = output / 'source'
    source_root.mkdir()
    contents = {}
    for source in sorted(TEMPLATES.glob('*.py')):
        shutil.copyfile(source, source_root / source.name)
        contents[source.name] = source.read_bytes()
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in contents.items()}
    snapshot = hashlib.sha256(b''.join(path.encode() + b'\0' + contents[path] for path in sorted(contents))).hexdigest()
    database = output / 'knowledge.sqlite3'
    db = sqlite3.connect(database)
    db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
    for scope in ('synthetic-current', 'synthetic-other'):
        db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)',
                   (scope, 'synthetic', str(source_root), 'synthetic-v1', snapshot, '2026-01-01'))

    def node(id_, title, summary, kind='architecture', path=None, line=None,
             confidence='confirmed', validity='current', scope='synthetic-current', layer='knowledge'):
        db.execute('''INSERT INTO nodes(scope_id,id,kind,layer,title,summary,confidence,validity,
            source_path,source_hash,line_start,line_end,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (scope, id_, kind, layer, title, summary, confidence, validity,
             path, hashes.get(path), line, line, '2026-01-01'))

    architecture = [
        ('a-admission', 'Command admission', 'Confirm is the only admission boundary. Reuse a pending request before preparing new content; send only after the local durable write succeeds.'),
        ('b-draft', 'Uncommitted input', 'Editing retains the raw reference and item list. Formatting and transmission happen only after an explicit Confirm action; edits do not rewrite pending bytes.'),
        ('c-local', 'Durable local commit', 'A saved reference and the exact outbound byte payload share one SQLite transaction. Failure of either insert leaves neither new row. This is the boundary to inspect for atomicity.'),
        ('d-wire', 'Wire representation', 'At admission, remove whitespace and uppercase the parcel reference, then encode compact deterministic JSON. It does not mutate the editable draft.'),
        ('e-delivery', 'Deferred delivery', 'A timeout leaves a pending payload. Repeating the checkout request ID replays its stored bytes before reading the possibly edited draft; acknowledge only after success.'),
        ('f-feedback', 'Operator feedback', 'The caller owns visual progress and error presentation. This fixture does not establish which screen renders a failed transfer; inspect real UI before making that claim.'),
    ]
    for id_, title, summary in architecture:
        node(id_, title, summary, confidence='uncertain' if id_ == 'f-feedback' else 'confirmed')
    node('c-local', 'Old local strategy', 'Alternate scope must not leak.', scope='synthetic-other')
    node('old-architecture', 'Legacy queue', 'Stale knowledge.', validity='stale')
    node('decision-raw', 'Preserve editable input', 'Keep user-entered draft text untouched; normalize a separate outbound value only on Confirm.', kind='decision')
    node('decision-replay', 'Stable pending identity', 'After a timeout use the original request ID and payload bytes; rebuilding from a changed draft risks a different remote operation.', kind='decision')
    code = [
        ('commands.py', 'commands.py', 'file', 'commands.py', 1, 'Coordinates explicit admission and retry.'),
        ('confirm', 'confirm', 'function', 'commands.py', 4, 'Reuse pending bytes, otherwise prepare and commit, then send and acknowledge.'),
        ('drafts.py', 'drafts.py', 'file', 'drafts.py', 1, 'Editable user input.'),
        ('Draft', 'Draft', 'class', 'drafts.py', 5, 'Owns raw reference and items.'),
        ('edit_reference', 'Draft.edit_reference', 'method', 'drafts.py', 9, 'Assign the input without formatting.'),
        ('protocol.py', 'protocol.py', 'file', 'protocol.py', 1, 'Outbound encoding boundary.'),
        ('prepare', 'prepare', 'function', 'protocol.py', 4, 'Normalize a copy and encode deterministic bytes.'),
        ('ledger.py', 'ledger.py', 'file', 'ledger.py', 1, 'Local durable state.'),
        ('Ledger', 'Ledger', 'class', 'ledger.py', 1, 'SQLite saved and outbox persistence.'),
        ('pending', 'Ledger.pending', 'method', 'ledger.py', 9, 'Read previously encoded bytes by request identity.'),
        ('commit', 'Ledger.commit', 'method', 'ledger.py', 13, 'Atomically insert saved reference and outbound bytes.'),
        ('acknowledge', 'Ledger.acknowledge', 'method', 'ledger.py', 19, 'Remove pending bytes after successful send.'),
        ('examples.py', 'examples.py', 'file', 'examples.py', 1, 'Display-only sample strings.'),
        ('parcel_example', 'parcel_reference_normalization_example', 'function', 'examples.py', 1, 'Return sample text; does not transform live input.'),
        ('checkout_example', 'checkout_timeout_example', 'function', 'examples.py', 5, 'Return sample text; no request dispatch or persistence.'),
    ]
    for id_, title, kind, path, line, summary in code:
        node(id_, title, summary, kind=kind, path=path, line=line, layer='code')
    # Same-word distractors model code search noise, without inventing another implementation.
    for index, term in enumerate(('parcel', 'reference', 'normalization', 'checkout', 'timeout')):
        node('noise-' + str(index), term + ' example', 'Documentation example; no runtime behavior established.', kind='finding')
    for id_, src, dst, kind, path in [
        ('01', 'confirm', 'a-admission', 'implements', 'commands.py'),
        ('02', 'edit_reference', 'b-draft', 'implements', 'drafts.py'),
        ('03', 'commit', 'c-local', 'implements', 'ledger.py'),
        ('04', 'prepare', 'd-wire', 'implements', 'protocol.py'),
        ('05', 'pending', 'e-delivery', 'implements', 'ledger.py'),
        ('06', 'a-admission', 'c-local', 'depends_on', 'commands.py'),
        ('07', 'a-admission', 'd-wire', 'depends_on', 'commands.py'),
        ('08', 'a-admission', 'e-delivery', 'depends_on', 'commands.py'),
        ('09', 'decision-raw', 'b-draft', 'constrains', 'drafts.py'),
        ('10', 'decision-replay', 'e-delivery', 'constrains', 'commands.py'),
        ('11', 'confirm', 'prepare', 'calls', 'commands.py'),
        ('12', 'confirm', 'commit', 'calls', 'commands.py'),
        ('13', 'confirm', 'pending', 'calls', 'commands.py'),
        ('14', 'confirm', 'acknowledge', 'calls', 'commands.py'),
        ('15', 'commands.py', 'confirm', 'contains', 'commands.py'),
        ('16', 'drafts.py', 'Draft', 'contains', 'drafts.py'),
        ('17', 'Draft', 'edit_reference', 'contains', 'drafts.py'),
        ('18', 'protocol.py', 'prepare', 'contains', 'protocol.py'),
        ('19', 'ledger.py', 'Ledger', 'contains', 'ledger.py'),
        ('20', 'Ledger', 'pending', 'contains', 'ledger.py'),
        ('21', 'Ledger', 'commit', 'contains', 'ledger.py'),
        ('22', 'Ledger', 'acknowledge', 'contains', 'ledger.py'),
    ]:
        db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,
            validity,source_path,source_hash,updated_at,layer)
            VALUES('synthetic-current',?,?,?,?,?,'confirmed','current',?,?,'2026-01-01',?)''',
            (id_, src, dst, kind, 'Synthetic source establishes ' + kind, path, hashes[path],
             'cross' if kind == 'implements' else 'knowledge' if kind in ('depends_on', 'constrains') else 'code'))
        db.execute('''INSERT INTO evidence(scope_id,id,edge_id,description,source_path,source_hash,validity,updated_at)
            VALUES('synthetic-current',?,?,?, ?,?,'current','2026-01-01')''',
            ('proof-' + id_, id_, 'Inspect the cited synthetic source before relying on this relationship.', path, hashes[path]))
    db.commit()
    db.close()
    receipt = dict(synthetic_fixture=True, database=str(database), source_root=str(source_root),
                   scope='synthetic-current', schema_version=3, schema_source=str(ROOT / 'schema.sql'),
                   revision='synthetic-v1', snapshot=snapshot,
                   tasks=[
                       'Parcel references must be normalized only when Confirm is pressed. Explain where to change this safely while preserving raw draft text and atomic saved-state/retry behavior. Verify the relevant sources.',
                       'A checkout request times out, the person edits the form, then repeats the request. Explain which boundaries preserve exact payload replay and where a change could break that guarantee. Verify the relevant sources.'
                   ])
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.evomneme-tests' / 'orientation')
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
