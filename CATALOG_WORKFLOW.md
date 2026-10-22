# Catalog and production update — 2026-10-22

Run once from `backend` before starting the updated app:

```powershell
.venv\Scripts\python.exe migrate_catalog.py
```

The script prefers `DATABASE_URL_UNPOOLED` for migrations and keeps the pooled
`DATABASE_URL` for application requests. `--dry-run` validates DDL and rolls back.
It creates `catalog_entries` and adds missing nullable social-integration columns
to products/settings from the merged code. Equivalent SQL is in `migrations/`.
Existing tables and business rows are preserved. Re-running is safe.

- One product represents the shared design. BOM rows have a primary material
  for costing and optional `alternative_material_ids` for other colors/brands.
  These options are stored in the existing JSON column; no column migration is needed.
- Each job saves its own total material quantities. Creating or editing a plan
  does not deduct stock. `reserved` holds the selected materials; `in_progress`
  consumes them. Completing directly from a plan also consumes once.
- Confirming an order no longer reserves its default BOM. Outstanding legacy
  order holds are released when creating/transitioning a job for that order.
  Existing movements remain in history. Already consumed stock is not restored.
- Pausing/resuming never consumes twice. Completed/cancelled jobs cannot reopen.
  A started job requires a separate stock adjustment for waste or corrections.
  Cancelling an unstarted order cancels its planned jobs and releases their holds;
  orders with jobs that already consumed materials require stock handling first.
- Editing a material balance writes an adjustment movement. A balance cannot be
  lower than its outstanding reservations.
- Price and lifecycle history begin recording with this update. Earlier changes
  that were never recorded cannot be reconstructed.
- Tags/types/units can be searched, created with Enter, or managed from each
  selector. Renaming updates existing references. Used entries cannot be deleted.
  `/catalog` provides a dedicated management page in the navigation.
- Job material JSON keeps raw per-product quantity, both wastage values, names,
  units and price at consumption. The production page groups quantities by product
  across colors/brands and shows actual material cost. Historical jobs without
  price snapshots display an explicit missing-history label.
- Costing, availability and material consumption share the same wastage and
  whole-piece rounding. Available stock excludes reservations.
- Without Cloudinary, uploads up to 2 MB are returned as data URLs and persisted
  with product images in SQL. Configured Cloudinary supports uploads up to 5 MB.

Regression checks:

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m unittest discover -s tests -v
```
