"""Database-local viewer settings, separate from graph and activity data."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time


DEFAULTS = {'gpu': False, 'worker': False, 'elementScale': 100,
            'experimentalPromptSeen': False}
ELEMENT_SCALES = {30, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300, 400}


def validate(values):
    """Reject unknown settings and coercions such as text or boolean scales."""
    if not isinstance(values, dict):
        raise ValueError('Viewer preferences must be an object')
    for key, value in values.items():
        if key not in DEFAULTS:
            raise ValueError('Unknown viewer preference: ' + key)
        if key == 'elementScale':
            if type(value) not in (int, float) or value not in ELEMENT_SCALES:
                raise ValueError('Invalid viewer elementScale')
        elif type(value) is not bool:
            raise ValueError('Viewer preference ' + key + ' must be boolean')
    return values


class ViewerPreferences:
    def __init__(self, database):
        self.path = Path(database).with_suffix('.viewer-settings.json')
        self.lock = threading.Lock()

    def read(self):
        """A missing file means defaults; unreadable or invalid files are errors."""
        try:
            raw = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return dict(DEFAULTS)
        try:
            saved = validate(json.loads(raw))
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid viewer settings file: ' + str(exc)) from exc
        return {**DEFAULTS, **saved}

    @contextmanager
    def write_lock(self):
        """Serialize writers across server instances/processes; reads stay inert."""
        with self.lock, self.path.with_suffix(self.path.suffix + '.lock').open('a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b'\0')
                    stream.flush()
            else:
                import fcntl
            deadline = time.monotonic() + 5
            while True:
                try:
                    if os.name == 'nt':
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise OSError('Viewer settings are busy; retry the change')
                    time.sleep(0.02)
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def request(self, values):
        if set(values) - {'updates'}:
            raise ValueError('Unknown viewer preferences request field')
        if 'updates' not in values:
            return self.read()
        updates = validate(values['updates'])
        if not updates:
            return self.read()
        with self.write_lock():
            merged = {**self.read(), **updates}
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                                 dir=self.path.parent,
                                                 prefix=self.path.name + '.',
                                                 suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(merged, stream, ensure_ascii=False, allow_nan=False, sort_keys=True)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return merged
