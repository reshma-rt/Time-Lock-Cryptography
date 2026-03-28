import sqlite3
import json
conn = sqlite3.connect('data/metadata.db')
cursor = conn.cursor()
cursor.execute('SELECT id, status, logs FROM files ORDER BY timestamp DESC LIMIT 1')
row = cursor.fetchone()
if row:
    print('LOGS FOR:', row[0], 'STATUS:', row[1])
    print(row[2])
else:
    print('Empty DB')
