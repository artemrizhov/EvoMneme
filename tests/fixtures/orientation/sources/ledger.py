class Ledger:
    def __init__(self, connection):
        self.db = connection
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS saved(request_id TEXT PRIMARY KEY, reference TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(request_id TEXT PRIMARY KEY, payload BLOB NOT NULL);
        ''')

    def pending(self, request_id):
        row = self.db.execute('SELECT payload FROM outbox WHERE request_id=?', (request_id,)).fetchone()
        return row[0] if row else None

    def commit(self, request_id, reference, payload):
        # Both writes commit together; either failing write rolls both back.
        with self.db:
            self.db.execute('INSERT INTO saved VALUES(?,?)', (request_id, reference))
            self.db.execute('INSERT INTO outbox VALUES(?,?)', (request_id, payload))

    def acknowledge(self, request_id):
        with self.db:
            self.db.execute('DELETE FROM outbox WHERE request_id=?', (request_id,))
