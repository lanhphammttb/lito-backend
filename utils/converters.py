"""Data conversion utilities."""
from datetime import date, datetime
from typing import Any, Dict, Optional
import json


def serialize_datetime(obj: Any) -> str:
    """Serialize datetime objects to ISO format string."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def to_dict(obj: Any, exclude: Optional[set] = None) -> Dict[str, Any]:
    """Convert object to dictionary."""
    exclude = exclude or set()
    
    if hasattr(obj, '__dict__'):
        result = {}
        for key, value in obj.__dict__.items():
            if key.startswith('_') or key in exclude:
                continue
            if isinstance(value, (datetime, date)):
                result[key] = value.isoformat()
            elif hasattr(value, '__dict__'):
                result[key] = to_dict(value, exclude)
            elif isinstance(value, list):
                result[key] = [
                    to_dict(item, exclude) if hasattr(item, '__dict__') else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
    
    if hasattr(obj, 'dict'):
        return obj.dict(exclude=exclude)
    
    return dict(obj) if isinstance(obj, dict) else {}


def from_dict(data: Dict[str, Any], cls: type) -> Any:
    """Create object from dictionary."""
    if hasattr(cls, 'parse_obj'):
        return cls.parse_obj(data)
    return cls(**data)


def json_dumps(obj: Any, **kwargs) -> str:
    """JSON serialize with datetime support."""
    return json.dumps(obj, default=serialize_datetime, **kwargs)


def json_loads(s: str) -> Any:
    """JSON deserialize."""
    return json.loads(s)


def model_to_response(model: Any, computed: Optional[Dict] = None) -> Dict[str, Any]:
    """Convert model to API response with computed fields."""
    data = to_dict(model)
    if computed:
        data.update(computed)
    return data
