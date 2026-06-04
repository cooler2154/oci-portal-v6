# OCI Instance Manager Portal — v2.0

Full-stack portal to manage Oracle Cloud Infrastructure compute instances.
**100 % Python — no Node.js, no npm, no build step.**

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.13 · FastAPI · SQLAlchemy (async) |
| Frontend | Jinja2 templates · Vanilla HTML/CSS/JS |
| Database | SQLite (dev) · PostgreSQL via psycopg v3 (prod) |
| OCI SDK | `oci` Python SDK — regional clients per request |

---

## What is fixed / included in v2.0

| Issue | Fix |
|-------|-----|
| Region → compartment mismatch | Every OCI call creates a **region-scoped client** — instances only come from the selected region |
| Operators saw all compartments | `list_compartments` now filters server-side by `user.scope` |
| Operators saw all instances | `list_instances` enforces scope AND tag rules server-side |
| Add user form broken | Full rewrite: username login (no email needed), correct validation |
| Action buttons unclear | Clear text buttons: **Start / Stop / Reboot** with icons |
| Edit/Delete unclear | Text buttons: **Edit** / **Delete** |
| OCI tag access control | Per-user tag rules (freeform + defined tags); instances not matching are hidden |
| Audit user filter broken | Dynamic dropdown populated from real DB entries via `/api/audit/users` |
| Audit not recorded | LOGIN, CREATE_USER, UPDATE_USER, DELETE_USER, START, STOP, SOFTRESET all written to `audit_log` table |
| No region selector | Region dropdown on Instances tab; compartments reload per region |

---

## Project structure

```
oci-portal/
├── Dockerfile
├── .gitignore
├── README.md
└── backend/
    ├── main.py                     app entry, startup, Jinja2 serving
    ├── requirements.txt
    ├── .env.example                copy → .env
    ├── core/
    │   ├── config.py               pydantic-settings: reads .env
    │   ├── logging_setup.py        app_logger (debug.log) + audit_logger (audit.log)
    │   └── oci_client.py           per-region OCI client factory
    ├── db/
    │   ├── database.py             async SQLAlchemy engine + get_db()
    │   └── models.py               User, AuditLog ORM tables
    ├── models/
    │   └── schemas.py              Pydantic request/response schemas + TagFilter
    ├── routers/
    │   ├── auth.py                 login (username), JWT, get_current_user, require_admin
    │   ├── users.py                CRUD — admin only, tag_filters serialised as JSON
    │   ├── instances.py            regions list, compartments (scoped), instances (scoped+tagged), actions
    │   ├── audit.py                query + CSV export, distinct-users endpoint
    │   └── debug.py                /health + log streaming (admin only)
    ├── templates/
    │   ├── index.html              base layout
    │   └── partials/
    │       ├── login.html          username + password form
    │       ├── topbar.html         app bar with user info + logout
    │       ├── tabbar.html         tab navigation (role-gated)
    │       ├── tab_instances.html  region / compartment / shape / status filters + table
    │       ├── tab_users.html      user form with scope picker + OCI tag rules
    │       ├── tab_audit.html      filterable audit table with region column
    │       ├── tab_debug.html      log console with level/module filters
    │       └── modals.html         action confirm, delete confirm, scope picker
    └── static/
        ├── css/portal.css          all styles
        └── js/portal.js            all frontend logic (810 lines, vanilla JS)
```

---

## Step-by-step implementation guide

### Step 1 — Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.11+ (3.13 recommended) | `python3 --version` |
| pip | latest | `pip --version` |
| psycopg (already installed) | 3.3.4 | `pip show psycopg` |
| OCI CLI (optional, for testing) | latest | `oci --version` |

No Node.js, no npm required.

---

### Step 2 — Configure OCI credentials

**Option A — API Key (local dev)**

1. Log in to OCI Console → **Identity & Security → Users → your user → API Keys → Add API Key**
2. Click **Generate API Key Pair** → Download private key
3. Copy the config snippet into `~/.oci/config`:

```ini
[DEFAULT]
tenancy=ocid1.tenancy.oc1..aaaa...
user=ocid1.user.oc1..aaaa...
fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
key_file=~/.oci/oci_api_key.pem
region=ap-sydney-1
```

4. Secure the key file:
```bash
chmod 600 ~/.oci/oci_api_key.pem
```

5. Verify it works:
```bash
oci iam compartment list --all 2>&1 | head -5
```

**Option B — Instance Principal (production inside OCI)**
- Set `OCI_INSTANCE_PRINCIPAL=1` in `.env`
- Create an OCI **Dynamic Group** matching your instance OCID:
  ```
  ANY {instance.id = 'ocid1.instance.oc1..xxx'}
  ```
- Create an **IAM Policy**:
  ```
  Allow dynamic-group oci-portal-dg to manage instances in tenancy
  Allow dynamic-group oci-portal-dg to read compartments in tenancy
  ```

---

### Step 3 — Set up the Python virtual environment

```bash
cd oci-portal/backend

# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate           # Windows PowerShell

# Verify you're inside the venv
which python   # should show .venv/bin/python
```

---

### Step 4 — Install dependencies

```bash
# Inside .venv
pip install -r requirements.txt
```

Key packages installed:
- `fastapi` + `uvicorn[standard]` — web framework + ASGI server
- `oci` — Oracle Cloud SDK
- `sqlalchemy` + `aiosqlite` — async ORM + SQLite driver
- `psycopg[binary]` — psycopg v3 for PostgreSQL (production)
- `python-jose[cryptography]` + `passlib[bcrypt]` — JWT + password hashing
- `jinja2` — HTML template rendering
- `pydantic-settings` — `.env` file loading

> **Note:** `psycopg2-binary` is NOT used. We use `psycopg[binary]` (psycopg v3)
> which is compatible with your installed psycopg 3.3.4.

---

### Step 5 — Configure the application

```bash
cp .env.example .env
```

Generate a secure secret key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Edit `.env` — minimum required settings:
```env
APP_ENV=development
SECRET_KEY=<paste-generated-key>
DATABASE_URL=sqlite+aiosqlite:///./oci_portal.db
OCI_INSTANCE_PRINCIPAL=0
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

---

### Step 6 — Run the portal

```bash
# From backend/ with .venv active
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

**On first start the app will:**
1. Create `oci_portal.db` (SQLite file)
2. Create all tables (`users`, `audit_log`)
3. Seed one admin user:
   - **Username:** `admin`
   - **Password:** `Admin1234!`

> ⚠️ Log in immediately and change the admin password via **User Management → Edit**.

---

### Step 7 — Using the portal

#### Instances tab
1. Select a **region** from the dropdown (e.g. `ap-sydney-1`)
2. Wait for **compartments** to load (only compartments in your scope appear)
3. Select a **compartment** — instances load automatically
4. Use **Start** / **Stop** / **Reboot** buttons — confirmation required

#### User Management tab (Admin only)
- **Add new user** → set name, username, role, compartment scope, allowed actions, tag rules
- **Edit** / **Delete** buttons on each row
- Role types:
  - **Admin** — full access, no restrictions
  - **Operator** — configurable scope + actions + tag filters
  - **Viewer** — read-only, sees only their scoped compartments

#### OCI Tag access rules (Operator / Viewer)
Add tag rules in the user form to restrict which instances a user can see and act on:

| Field | Example | Effect |
|-------|---------|--------|
| Namespace (blank) | — | Freeform tag |
| Key | `Environment` | Tag key |
| Value | `dev` | Exact match required |

Example: User with rule `Environment=dev` only sees instances that have `Environment=dev` in their freeform tags.

For **defined tags** (e.g. Oracle-Tags namespace):
- Namespace: `Oracle-Tags`
- Key: `CreatedBy`
- Value: `team-infra`

#### Audit log tab
- Filters: by user, action type, region, free-text search
- **All users** dropdown is populated from real audit records
- **Operators** only see their own audit entries
- CSV export for compliance

#### Debug tab (Admin only)
- Live log stream from `debug.log`
- Filter by level (DEBUG / INFO / WARN / ERROR) and module
- Red badge on tab shows current ERROR count

---

### Step 8 — Compartment scope for operators

When creating or editing an Operator:

1. Type `all` in the scope field → operator sees all compartments
2. **Or** click **"Pick from compartments"** (load a region on Instances tab first)
3. **Or** paste comma-separated OCIDs directly:
   ```
   ocid1.compartment.oc1..aaaa,ocid1.compartment.oc1..bbbb
   ```

The backend enforces scope on both `list_compartments` and `list_instances` endpoints.

---

### Step 9 — Production: switch to PostgreSQL

**Create the database:**
```bash
psql -U postgres << 'SQL'
CREATE DATABASE oci_portal;
CREATE USER oci_user WITH PASSWORD 'YourStrongPassword123!';
GRANT ALL PRIVILEGES ON DATABASE oci_portal TO oci_user;
SQL
```

**Update `.env`:**
```env
DATABASE_URL=postgresql+psycopg://oci_user:YourStrongPassword123!@localhost:5432/oci_portal
APP_ENV=production
```

Tables are created automatically on startup (same as SQLite).

---

### Step 10 — Docker build and run

```bash
# Build (from project root — where Dockerfile lives)
docker build -t oci-portal .

# Run with local OCI config (dev/test)
docker run -p 8000:8000 \
  -v ~/.oci:/root/.oci:ro \
  -e SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e APP_ENV=development \
  oci-portal

# Run in production (OCI Instance Principal — no .pem needed)
docker run -p 8000:8000 \
  -e OCI_INSTANCE_PRINCIPAL=1 \
  -e APP_ENV=production \
  -e SECRET_KEY=<your-32-char-secret> \
  -e DATABASE_URL=postgresql+psycopg://user:pw@db-host/oci_portal \
  oci-portal
```

---

### Step 11 — Deploy to OCI Container Instances

```bash
# 1. Log in to OCI Container Registry
docker login <region>.ocir.io -u '<tenancy-namespace>/<username>'

# 2. Tag and push the image
docker tag oci-portal <region>.ocir.io/<namespace>/oci-portal:v2
docker push <region>.ocir.io/<namespace>/oci-portal:v2

# 3. Create a Container Instance
oci container-instances container-instance create \
  --compartment-id $COMPARTMENT_ID \
  --display-name oci-portal \
  --availability-domain <AD-name> \
  --shape CI.Standard.E4.Flex \
  --shape-config '{"ocpus":1,"memoryInGBs":4}' \
  --vnics '[{"subnetId":"<subnet-ocid>"}]' \
  --containers '[{
    "imageUrl":"<region>.ocir.io/<ns>/oci-portal:v2",
    "displayName":"oci-portal",
    "environmentVariables":{
      "OCI_INSTANCE_PRINCIPAL":"1",
      "APP_ENV":"production",
      "SECRET_KEY":"<your-secret>",
      "DATABASE_URL":"postgresql+psycopg://user:pw@host/oci_portal",
      "ALLOWED_ORIGINS":"https://your-domain.com"
    }
  }]'
```

---

### Step 12 — Verification checklist

```bash
# Backend health check
curl http://localhost:8000/api/debug/health
# Expected: {"status":"ok","env":"development"}

# Login (returns JWT)
curl -X POST http://localhost:8000/api/auth/login \
  -d "username=admin&password=Admin1234!" \
  -H "Content-Type: application/x-www-form-urlencoded"

# List regions (no auth needed after login)
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/regions

# Interactive API docs (dev mode only)
open http://localhost:8000/docs
```

---

## API reference

| Method | Endpoint | Auth required | Description |
|--------|----------|--------------|-------------|
| POST | `/api/auth/login` | None | Login → JWT |
| GET | `/api/auth/me` | Any | Current user |
| GET | `/api/users` | Admin | List all users |
| POST | `/api/users` | Admin | Create user (with tag rules) |
| PATCH | `/api/users/{id}` | Admin | Update user |
| DELETE | `/api/users/{id}` | Admin | Delete user |
| GET | `/api/regions` | Any | OCI region list |
| GET | `/api/compartments?region=` | Any (scoped) | Compartments for region |
| GET | `/api/instances?compartment_id=&region=` | Any (scoped+tagged) | Instances |
| POST | `/api/instances/{id}/action?region=` | Op/Admin | Start/Stop/Reboot |
| GET | `/api/audit/users` | Op/Admin | Distinct usernames in audit |
| GET | `/api/audit` | Op/Admin | Query audit log |
| GET | `/api/audit/export` | Admin | Download CSV |
| GET | `/api/debug/health` | None | Health check |
| GET | `/api/debug/logs` | Admin | Stream log entries |

---

## Security checklist

- [ ] Change default admin password on first login
- [ ] Generate a strong `SECRET_KEY` (32+ random hex chars)
- [ ] Add `.env`, `*.pem`, `.oci/` to `.gitignore` — never commit
- [ ] Set `APP_ENV=production` to disable `/docs` endpoint
- [ ] Use Instance Principal auth in production (no static keys)
- [ ] Put an HTTPS load balancer or reverse proxy in front
- [ ] Restrict `ALLOWED_ORIGINS` to your exact frontend domain
- [ ] Scope operators to their compartments — never leave all operators on `scope=all`
- [ ] Add OCI tag rules for fine-grained instance access
- [ ] Review IAM policies — give the portal the minimum OCI permissions needed
