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
polls HTTP endpoints. The in-memory WebSocket manager only reaches connections
on its own instance; it is not a reliable cross-instance notification transport.

Browser notifications use Firebase Cloud Messaging. Set backend Production
`FIREBASE_CREDENTIALS_JSON` to the complete service account JSON for the same
Firebase project as the frontend and redeploy. The local file fallback is
`FIREBASE_CREDENTIALS` or `firebase-adminsdk.json`; deployment must not depend on
an untracked local file. Keep credentials outside Git. Frontend requires
`VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_APP_ID`,
`VITE_FIREBASE_MESSAGING_SENDER_ID`, and `VITE_FIREBASE_VAPID_KEY`.

Users enable browser notifications explicitly on the Notifications page. A
granted permission alone is insufficient: the device token must be registered
with the current user's account. Registration is refreshed after login/reload.
`GET /notifications/status` checks server configuration and the account's device
count. `POST /notifications/test` sends only to that account. `/test-email`
tests SMTP separately. Send results count actual FCM acceptances, report failed
devices, and remove only definitely expired registrations. FCM acceptance is
not proof of OS display or of the user reading the message. Check browser and
OS permissions/Do Not Disturb when validation succeeds but no banner appears.

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
