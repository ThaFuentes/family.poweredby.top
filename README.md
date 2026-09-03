# family.poweredby.top

Household operating system — scan-driven, multi-tenant, private per family.

Not a grocery app. Not a tool tracker. Not a vehicle log. One household brain:

- Groceries & consumables (UPC consume / restock)
- Tools & equipment (QR, oil/fuel, maintenance)
- Vehicles (oil, filters, mileage, reminders)
- Photos, notes, reminders
- Roles: admin / member / child

## Stack (matches the rest of poweredby.top)

- Flask (`main.py` laptop, `passenger_wsgi.py` HostM)
- `app/__init__.py` factory, `SITE_MODE=family`
- MariaDB via root `dbconnector.py`
- `poweredbytop/` security wrapper
- Household row isolation on every query

## Laptop

```bash
cp .env.example .env
# edit SECRET_KEY
chmod +x start_local.sh
./start_local.sh
```

Open http://127.0.0.1:5060 — first visit registers a household admin.

## HostM

See `docs/HOST_DEPLOY.md`. Path: `/home/ua882038/public_html/family.poweredby.top`
