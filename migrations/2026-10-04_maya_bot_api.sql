-- Family OS: Maya bot API + owner permission checklist + recycle bin + file versions
-- 2026-10-04. MariaDB/MySQL. Idempotent: safe to run more than once.
-- The app also creates/evolves these on boot (app/builddb/table_maya_bot.py),
-- so running this by hand is optional; use it if boot-time builds are off.

CREATE TABLE IF NOT EXISTS maya_bot_accounts (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  household_id INT NOT NULL,
  user_id INT NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  set_by INT NULL,
  created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_maya_bot_accounts_household (household_id),
  CONSTRAINT fk_maya_acct_house FOREIGN KEY (household_id) REFERENCES households(id) ON DELETE CASCADE,
  CONSTRAINT fk_maya_acct_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS maya_bot_permissions (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  household_id INT NOT NULL,
  user_id INT NOT NULL,
  perm VARCHAR(64) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  expires_at DATETIME NULL,
  updated_by INT NULL,
  updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_maya_perm (household_id, user_id, perm),
  KEY idx_maya_perm_user (household_id, user_id),
  KEY idx_maya_perm_expiry (enabled, expires_at),
  CONSTRAINT fk_maya_perm_house FOREIGN KEY (household_id) REFERENCES households(id) ON DELETE CASCADE,
  CONSTRAINT fk_maya_perm_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS maya_bot_perm_log (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  household_id INT NOT NULL,
  user_id INT NULL,
  changed_by INT NULL,
  perm VARCHAR(64) NOT NULL,
  old_value TINYINT(1) NULL,
  new_value TINYINT(1) NULL,
  high_risk TINYINT(1) NOT NULL DEFAULT 0,
  confirmed_with VARCHAR(16) NULL,
  ip VARCHAR(64) NULL,
  created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_maya_perm_log_house (household_id, created_at),
  CONSTRAINT fk_maya_log_house FOREIGN KEY (household_id) REFERENCES households(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS household_trash (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  household_id INT NOT NULL,
  target_table VARCHAR(40) NOT NULL,
  target_id INT NOT NULL,
  label VARCHAR(240) NULL,
  rows_json JSON NULL,
  files_json JSON NULL,
  deleted_by INT NULL,
  via VARCHAR(16) NULL,
  deleted_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  restored_at DATETIME NULL,
  restored_by INT NULL,
  purged_at DATETIME NULL,
  purged_by INT NULL,
  KEY idx_household_trash_house (household_id, deleted_at),
  CONSTRAINT fk_trash_house FOREIGN KEY (household_id) REFERENCES households(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS household_file_versions (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  household_id INT NOT NULL,
  kind VARCHAR(20) NOT NULL,
  row_id INT NOT NULL,
  stored_rel VARCHAR(400) NOT NULL,
  archived_path VARCHAR(500) NOT NULL,
  original_name VARCHAR(200) NULL,
  mime VARCHAR(80) NULL,
  reason VARCHAR(16) NULL,
  created_by INT NULL,
  created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  restored_at DATETIME NULL,
  KEY idx_file_versions_row (household_id, kind, row_id),
  CONSTRAINT fk_filever_house FOREIGN KEY (household_id) REFERENCES households(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Designate Maya = bot user 'grokbots' in household 'fuentes' (only if it is a bot
-- and no Maya is set yet). Permissions need no seed rows: missing row = catalog
-- default (normal ON, high-risk OFF). The owner changes them on /maya-permissions.
INSERT INTO maya_bot_accounts (household_id, user_id, enabled)
SELECT u.household_id, u.id, 1
FROM users u JOIN households h ON h.id = u.household_id
WHERE LOWER(h.handle) = 'fuentes' AND LOWER(u.username) = 'grokbots' AND u.is_bot = 1
  AND NOT EXISTS (SELECT 1 FROM maya_bot_accounts m WHERE m.household_id = u.household_id)
LIMIT 1;

-- Auto-off timers (added later the same day). For a table created before this
-- column existed (MariaDB 10.3+ supports IF NOT EXISTS here):
ALTER TABLE maya_bot_permissions ADD COLUMN IF NOT EXISTS expires_at DATETIME NULL AFTER enabled;
