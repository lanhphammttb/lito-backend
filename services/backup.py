"""Consistent application data exports and restoration into an empty database."""
import base64
import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal
from sqlalchemy import MetaData, select, text
from utils.datetime import utcnow


def _encode(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {'$bytes': base64.b64encode(value).decode('ascii')}
    raise TypeError(f'Unsupported backup value: {type(value).__name__}')


def _digest(payload):
    content = {key: value for key, value in payload.items() if key != 'sha256'}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), default=_encode, allow_nan=False).encode()).hexdigest()


def export_snapshot(engine):
    connection = engine.connect()
    try:
        if engine.dialect.name == 'postgresql':
            connection = connection.execution_options(isolation_level='REPEATABLE READ')
        with connection.begin():
            metadata = MetaData()
            metadata.reflect(bind=connection)
            tables = {}
            for table in metadata.sorted_tables:
                statement = select(table)
                if table.primary_key.columns:
                    statement = statement.order_by(*table.primary_key.columns)
                tables[table.name] = [dict(row) for row in connection.execute(statement).mappings()]
        payload = {'format': 'lito-database-backup', 'version': 1,
                   'created_at': utcnow().isoformat(), 'tables': tables,
                   'row_counts': {name: len(rows) for name, rows in tables.items()}}
        # Normalize dates and other SQL values before hashing and downloading.
        payload = json.loads(json.dumps(payload, ensure_ascii=False, default=_encode, allow_nan=False))
        payload['sha256'] = _digest(payload)
        return payload
    finally:
        connection.close()


def restore_snapshot(engine, payload):
    """Refuse to overwrite existing data; restore all rows in one transaction."""
    if payload.get('format') != 'lito-database-backup' or payload.get('version') != 1:
        raise ValueError('Định dạng bản sao lưu không được hỗ trợ')
    if payload.get('sha256') != _digest(payload):
        raise ValueError('Bản sao lưu không toàn vẹn')
    with engine.begin() as connection:
        metadata = MetaData()
        metadata.reflect(bind=connection)
        if set(payload['tables']) != set(metadata.tables):
            raise ValueError('Cấu trúc cơ sở dữ liệu đích không khớp bản sao lưu')
        for table in metadata.sorted_tables:
            if connection.execute(select(table).limit(1)).first() is not None:
                raise ValueError('Chỉ khôi phục vào cơ sở dữ liệu trống')
        for table in metadata.sorted_tables:
            rows = payload['tables'][table.name]
            if len(rows) != payload['row_counts'].get(table.name):
                raise ValueError('Số bản ghi không khớp bản sao lưu')
            decoded = []
            for row in rows:
                if set(row) != set(table.columns.keys()):
                    raise ValueError('Cột dữ liệu không khớp cơ sở dữ liệu đích')
                item = dict(row)
                for column in table.columns:
                    value = item[column.name]
                    if value is None:
                        continue
                    try:
                        python_type = column.type.python_type
                    except NotImplementedError:
                        continue
                    if python_type in (datetime, date, time) and isinstance(value, str):
                        item[column.name] = python_type.fromisoformat(value)
                    elif python_type is Decimal:
                        item[column.name] = Decimal(value)
                    elif python_type is bytes and isinstance(value, dict):
                        item[column.name] = base64.b64decode(value['$bytes'])
                decoded.append(item)
            if decoded:
                connection.execute(table.insert(), decoded)
            if engine.dialect.name == 'postgresql':
                for column in table.primary_key.columns:
                    sequence = connection.execute(text('SELECT pg_get_serial_sequence(:table, :column)'),
                        {'table': table.name, 'column': column.name}).scalar()
                    if sequence:
                        highest = max((row[column.name] for row in rows), default=0)
                        connection.execute(text('SELECT setval(:sequence, :value, :called)'),
                            {'sequence': sequence, 'value': max(highest, 1), 'called': bool(highest)})
    return payload['row_counts']
