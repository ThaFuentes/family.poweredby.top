# Family OS — GitHub + HostM deploy

Repo: `https://github.com/ThaFuentes/family.poweredby.top`  
Host: `/home/ua882038/public_html/family.poweredby.top`  
Branch: `main`

Operator protocol (paste PAT in chat → AI pushes → AI returns HostM URL+commands → revoke): see `AGENTS.md`.

**Never** put a live PAT in this file.

## Laptop push (AI / local)

```bash
cd /home/clarkkent/pyprojects/family.poweredby.top
# one-off URL — do not save as origin
git push "https://x-access-token:YOUR_PAT@github.com/ThaFuentes/family.poweredby.top.git" HEAD:main
```

## First-time HostM (folder has no .git)

cPanel: create subdomain `family.poweredby.top`, a Python app on that document root, and a MariaDB database. Put MYSQL_* + SECRET_KEY in `.env` on the host (never commit it).

```bash
mkdir -p /home/ua882038/public_html/family.poweredby.top
cd /home/ua882038/public_html/family.poweredby.top
git init
git fetch "https://x-access-token:YOUR_PAT@github.com/ThaFuentes/family.poweredby.top.git" main
git checkout FETCH_HEAD -- .
# keep host-only files if they already exist; on a blank folder the checkout is the first copy
mkdir -p tmp uploads logs
touch tmp/restart.txt
```

If that folder has no `.git`, locate clones first:

```bash
ls ~/repositories; find ~ -name .git -path '*family*'
```

## HostM pull (paste in cPanel / SSH terminal)

```bash
cd /home/ua882038/public_html/family.poweredby.top
git remote -v
git fetch "https://x-access-token:YOUR_PAT@github.com/ThaFuentes/family.poweredby.top.git" main
git checkout FETCH_HEAD -- \
  AGENTS.md \
  README.md \
  LICENSE \
  main.py \
  dbconnector.py \
  requirements.txt \
  app/ \
  poweredbytop/ \
  docs/
mkdir -p tmp
touch tmp/restart.txt
```

If the host clone already tracks this repo and you want the full branch:

```bash
cd /home/ua882038/public_html/family.poweredby.top
git fetch "https://x-access-token:YOUR_PAT@github.com/ThaFuentes/family.poweredby.top.git" main:main
git checkout main
git reset --hard main
mkdir -p tmp
touch tmp/restart.txt
```

Do **not** overwrite host-only files: `passenger_wsgi.py`, `.htaccess`, `.env`, `uploads/`.

After HostM succeeds: revoke the PAT at https://github.com/settings/tokens
