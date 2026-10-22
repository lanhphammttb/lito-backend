"""Reusable tags, material types and units, persisted in SQL."""
import json
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField, Session, select
from config.database import engine
from models.user import User
from models.product import ProductTable
from models.material import MaterialTable
from services.auth import get_current_user

class CatalogEntry(SQLModel, table=True):
    __tablename__ = "catalog_entries"
    kind: str = SQLField(primary_key=True)
    name: str = SQLField(primary_key=True)
    unit_type: str = "continuous"

class EntryInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    unit_type: Literal["continuous", "piece"] = "continuous"

router = APIRouter()
KINDS = {"tags", "material-types", "units"}
DEFAULTS = {
    "tags": [], "material-types": [("len", "continuous"), ("phụ kiện", "continuous")],
    "units": [("gram", "continuous"), ("m", "continuous"), ("ml", "continuous"), ("cái", "piece"), ("cặp", "piece"), ("bộ", "piece")],
}

def check_kind(kind):
    if kind not in KINDS:
        raise HTTPException(404, "Loại danh mục không tồn tại")

def used_names(session, kind):
    if kind == "tags":
        return {tag: "continuous" for p in session.exec(select(ProductTable)).all() for tag in json.loads(p.tags_json or "[]")}
    return {getattr(m, "unit" if kind == "units" else "type"): m.unit_type for m in session.exec(select(MaterialTable)).all()}

@router.get("/{kind}")
async def list_entries(kind: str, user: User = Depends(get_current_user)):
    check_kind(kind)
    with Session(engine) as session:
        names = {name: unit_type for name, unit_type in DEFAULTS[kind]}
        names.update(used_names(session, kind))
        names.update({r.name: r.unit_type for r in session.exec(select(CatalogEntry).where(CatalogEntry.kind == kind)).all()})
        return [{"name": name, "unit_type": unit_type} for name, unit_type in sorted(names.items())]

@router.post("/{kind}")
async def create_entry(kind: str, payload: EntryInput, user: User = Depends(get_current_user)):
    check_kind(kind)
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Tên không được để trống")
    with Session(engine) as session:
        # Reuse a matching entry regardless of casing; Enter never creates duplicates.
        entries = await list_entries(kind, user)
        name = next((r["name"] for r in entries if r["name"].casefold() == name.casefold()), name)
        row = session.get(CatalogEntry, (kind, name))
        if row:
            return row.model_dump()
        inferred_type = next((r["unit_type"] for r in entries if r["name"] == name), payload.unit_type)
        row = CatalogEntry(kind=kind, name=name, unit_type=inferred_type)
        session.add(row)
        session.commit()
        return {"name": name, "unit_type": inferred_type}

@router.put("/{kind}/{name:path}")
async def rename_entry(kind: str, name: str, payload: EntryInput, user: User = Depends(get_current_user)):
    check_kind(kind)
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(422, "Tên không được để trống")
    with Session(engine) as session:
        entries = await list_entries(kind, user)
        if new_name.casefold() != name.casefold() and any(r["name"].casefold() == new_name.casefold() for r in entries):
            raise HTTPException(409, "Tên đã tồn tại")
        if kind == "tags":
            for product in session.exec(select(ProductTable)).all():
                tags = json.loads(product.tags_json or "[]")
                if name in tags:
                    product.tags_json = json.dumps([new_name if t == name else t for t in tags])
                    session.add(product)
        else:
            for mat in session.exec(select(MaterialTable)).all():
                attr = "unit" if kind == "units" else "type"
                if getattr(mat, attr) == name:
                    if kind == "units" and mat.reserved_qty > 0 and mat.unit_type != payload.unit_type:
                        raise HTTPException(409, "Không đổi cách tính đơn vị khi nguyên liệu đang được giữ chỗ")
                    setattr(mat, attr, new_name)
                    if kind == "units":
                        mat.base_unit = new_name
                        mat.unit_type = payload.unit_type
                    session.add(mat)
        old = session.get(CatalogEntry, (kind, name))
        if old:
            session.delete(old)
            session.flush()
        session.add(CatalogEntry(kind=kind, name=new_name, unit_type=payload.unit_type))
        session.commit()
    from services.product import clear_product_cost_cache
    clear_product_cost_cache()
    return {"name": new_name, "unit_type": payload.unit_type}

@router.delete("/{kind}/{name:path}")
async def delete_entry(kind: str, name: str, user: User = Depends(get_current_user)):
    check_kind(kind)
    with Session(engine) as session:
        if name in used_names(session, kind):
            raise HTTPException(409, "Giá trị đang được sử dụng; hãy đổi tên hoặc bỏ khỏi sản phẩm/nguyên liệu trước")
        if name in dict(DEFAULTS[kind]):
            raise HTTPException(409, "Giá trị mặc định được giữ để dùng chung")
        row = session.get(CatalogEntry, (kind, name))
        if row:
            session.delete(row)
            session.commit()
    return {"ok": True}
