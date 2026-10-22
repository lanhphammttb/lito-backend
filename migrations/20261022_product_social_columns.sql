-- PostgreSQL: nullable fields used by the social integration from the merged code.
ALTER TABLE products ADD COLUMN IF NOT EXISTS facebook_post_id TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS instagram_post_id TEXT;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS facebook_page_id TEXT;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS facebook_page_name TEXT;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS facebook_page_access_token TEXT;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS facebook_app_id TEXT;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS facebook_app_secret TEXT;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS instagram_business_account_id TEXT;
