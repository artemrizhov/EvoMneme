"""Create a separate disposable CLI probe; never modifies earlier probe artifacts."""
import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme_connection import run_setup as connect
from evomneme_install import run_setup as install


def build(output):
    output = Path(output).resolve()
    area = (ROOT / '.evomneme-tests').resolve()
    if not output.is_relative_to(area):
        raise ValueError('Navigation fixtures must stay in the excluded project test area')
    spec = importlib.util.spec_from_file_location('orientation_source_fixture',
        ROOT / 'tests/fixtures/orientation/build_fixture.py')
    source_fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source_fixture)
    receipt = source_fixture.build(output)  # Refuses every nonempty existing output.
    database = Path(receipt['database'])
    db = sqlite3.connect(database)
    try:
        with db:
            db.execute("INSERT INTO metadata VALUES('project_identity','synthetic-navigation-probe')")
            # The fixture is one project, not a pair of linked Git worktrees.
            db.execute('UPDATE scopes SET worktree=?', (str(output),))
            db.execute('''INSERT INTO nodes(scope_id,id,kind,layer,title,summary,confidence,validity,updated_at)
                VALUES(?,'system','project','knowledge','Shipment submission',
                'Accept editable shipment drafts and submit explicit commands. Separate input editing, admission, wire encoding, local durable state and deferred delivery so retries preserve the submitted operation.',
                'confirmed','current','2026-01-01')''', (receipt['scope'],))
            responsibilities = [
                ('a-admission', 'Accept explicit submission and coordinate preparation, persistence and send.'),
                ('b-draft', 'Retain editable user input before explicit submission.'),
                ('c-local', 'Keep submitted state and pending transmission bytes durable together.'),
                ('d-wire', 'Construct the outbound representation at the admission boundary.'),
                ('e-delivery', 'Resume pending transmission after an interrupted attempt.'),
            ]
            for index, (target, summary) in enumerate(responsibilities):
                db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,layer,summary,
                    confidence,validity,updated_at) VALUES(?,?,'system',?,'coordinates','knowledge',?,
                    'confirmed','current','2026-01-01')''',
                    (receipt['scope'], 'system-responsibility-' + str(index), target, summary))
    finally:
        db.close()
    # This explicit invalid Git marker isolates the synthetic project from the
    # tool repository above it. It intentionally produces an unverified-checkpoint warning.
    (output / '.git').write_text('gitdir: missing-synthetic-git\n', encoding='utf-8')
    activate = output / '.evomneme' / 'bin'
    messages = io.StringIO()
    previous = Path.cwd()
    try:
        os.chdir(output)
        with redirect_stdout(messages):
            connect(argparse.Namespace(project=output, database=database, scope=receipt['scope'],
                root_id='system', canonical_root=output, shell=None))
            install(argparse.Namespace(bin_dir=None, activate=activate))
    finally:
        os.chdir(previous)
    result = dict(project_root=str(output), receipt=str(output / 'receipt.json'),
                  connection=str(output / '.evomneme' / 'connection.json'),
                  activation_powershell=str(activate / 'activate.ps1'),
                  activation_posix=str(activate / 'activate.sh'),
                  source_root=receipt['source_root'], database=str(database), tasks=receipt['tasks'])
    (output / 'navigation-probe.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.evomneme-tests' / 'navigation-probe')
    print(json.dumps(build(parser.parse_args().output), indent=2))
