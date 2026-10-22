"""Restore a backup into a separately configured, empty database only."""
import argparse
import json
import os
import secrets
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('backup_file', type=Path)
args = parser.parse_args()
target = os.getenv('LITO_RESTORE_DATABASE_URL')
if not target:
    parser.error('Set LITO_RESTORE_DATABASE_URL to a new empty database')
os.environ.update(DATABASE_URL=target, USE_MONGO='false', SENTRY_DSN='')
os.environ.setdefault('JWT_SECRET', secrets.token_urlsafe(32))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # Register every application model; do not start the app or seed users.
from sqlmodel import SQLModel
from config.database import engine
from services.backup import restore_snapshot

try:
    SQLModel.metadata.create_all(engine)
    counts = restore_snapshot(engine, json.loads(args.backup_file.read_text(encoding='utf-8')))
    print(f'Restored {sum(counts.values())} rows across {len(counts)} tables')
finally:
    engine.dispose()
