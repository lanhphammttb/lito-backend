# Vercel deployment

Backend project: `hala-handmade-api`; root directory: `backend` when deploying
from the parent repository, or `.` from the standalone `lito-backend` repository.
Run `npx vercel deploy --prod` from this directory. Python 3.12 is pinned.

The production database is Neon PostgreSQL (`hala-handmade-db`, free plan,
Singapore), connected through Vercel Marketplace. `DATABASE_URL` is injected
by the integration. SQLite and missing database configuration fail on Vercel.
Local `.env` files and database files are excluded from deployment.

Required environment variables: `JWT_SECRET`, `DATABASE_URL`, `CORS_ORIGINS`.
Keep `USE_MONGO=false`, `AUTO_INIT_DB_ON_STARTUP=false` and
`AUTO_SEED_DATA_ON_STARTUP=false`. Configure Cloudinary variables for uploads.
Do not share the production database with preview deployments.

GA4 requires `GA4_CREDENTIALS_JSON` in the backend's production environment:
set it to the complete JSON of the GA4 service account, then redeploy. Keep
private keys out of Git and deployment files. `GA4_PROPERTY_ID` is the numeric
property ID (defaults to the existing property `536976944`). Enable the Google
Analytics Data API and grant the service account Viewer access in that GA4
property. Local development also supports a file selected by
`GOOGLE_APPLICATION_CREDENTIALS`, or `config/ga4_credentials.json`.
Missing or invalid credentials return an actionable 503 response; GA4 routes
require login. Business data and the rest of the app continue to work without GA4.

Initialize the schema explicitly with `config.database.create_db_and_tables()`
after importing `main` to register every table. Do not seed sample business data.
For an existing PostgreSQL database, take a backup and restore/copy its data
before changing the frontend API URL. Keep the source database intact and
verify row counts and sequences after migration. Do not substitute old local
SQLite snapshots for the live database without verifying their freshness.

Set frontend `VITE_API_URL` to the backend deployment URL and
`VITE_ENABLE_WEBSOCKET=false`, then rebuild the frontend. The notification bell
already polls HTTP endpoints. Vercel Functions do not host WebSocket servers.

Production frontend: https://admin.litohandmade.com
Production backend: https://hala-handmade-api.vercel.app
The frontend Vercel project is `hala-handmade`, using Vite and root directory
`frontend`. Deploy it from the parent repository (not from `frontend`, which
would make Vercel look for `frontend/frontend`). The parent `.vercelignore`
excludes backend files, local environments, and databases from frontend uploads.
When not linked at the repository root, set `VERCEL_PROJECT_ID` and
`VERCEL_ORG_ID` from `frontend/.vercel/project.json` before running
`npx vercel deploy --prod --yes` from the repository root.

The database currently contains the owner accounts initialized from existing
local bootstrap configuration. Historical business data has not been migrated.

Legacy endpoints still use mutable lists. On Vercel, requests refresh these
lists from PostgreSQL and hold a transaction-scoped advisory lock across the
request. This preserves consistency between instances, but serializes requests
and limits throughput. Replace legacy lists with direct SQL queries before
scaling traffic. Health and CORS preflight requests bypass the lock.

Verification: `/health` checks a real database connection; `/products` requires
authentication. Run `python -m unittest discover -s tests -v` locally.
