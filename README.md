# Call Centre Workforce Simulator

A Python + Streamlit tool for operational and strategic workforce planning in contact centres. Models demand, Erlang C queueing, roster optimisation, discrete event simulation, and multi-month workforce projections from a single interface.

---

## What it does

- **Demand modelling** — upload historical call volume CSVs or use a synthetic demand curve; interval-level (15 min default) across single or multi-day horizons
- **Erlang C staffing** — calculates net and paid headcount requirements with service level and occupancy predictions
- **Roster generation** — shift template builder, LP and greedy optimisers, coverage gap analysis
- **DES validation** — SimPy discrete event simulation validates Erlang predictions under realistic call dynamics
- **Scenario testing** — volume, AHT, and patience shocks applied across multiple scenarios
- **Workforce supply analysis** — import actual staffing rosters, compare against requirements, derive observed shrinkage from activity data
- **Strategic planning** — cohort-based attrition/hiring/ramp model across a monthly horizon
- **Hiring optimisation** — MILP-based cost-optimal hiring plan with scenario robustness analysis
- **Persistent state** — all widget values and computed results survive browser refreshes

---

## Setup (10 minutes)

### Prerequisites

- Python 3.9 or later (3.11 recommended)
- `git` to clone the repository
- A deployment key from the administrator (see below)

---

### Option A — Run locally (no Docker)

**1. Clone the repository**

```bash
git clone <repository-url>
cd workforce-simulator
```

**2. Create a virtual environment and install dependencies**

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**3. Set your deployment key**

```bash
cp .env.example .env
```

Open `.env` and replace `your_deployment_key_here` with the key provided by the administrator.

To load it before running Streamlit:

```bash
export $(cat .env | xargs)      # macOS / Linux
```

On Windows (PowerShell):

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match "^([^#][^=]*)=(.*)$") { [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2]) }
}
```

**4. Configure user credentials**

```bash
cp auth/credentials.yaml.example auth/credentials.yaml
```

Open `auth/credentials.yaml` and:

- Replace the example usernames, names, and email addresses with your own
- Replace each `password` value with a bcrypt hash. Generate one with:

```bash
python -c "import bcrypt; pw = input('Password: ').encode(); print(bcrypt.hashpw(pw, bcrypt.gensalt()).decode())"
```

- Replace `REPLACE_WITH_A_LONG_RANDOM_SECRET_STRING` in the `cookie.key` field with a random secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**5. Run the app**

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

### Option B — Docker (recommended for deployment)

**1. Clone and configure**

```bash
git clone <repository-url>
cd workforce-simulator

cp .env.example .env
# → fill in DEPLOYMENT_KEY

cp auth/credentials.yaml.example auth/credentials.yaml
# → add users, set bcrypt passwords, set cookie.key
```

**2. Start the container**

```bash
docker-compose up --build
```

Open [http://localhost:8501](http://localhost:8501). The app will restart automatically if the container is rebooted (`restart: unless-stopped`).

Simulation state is persisted to `./state/` on the host and survives container rebuilds. Credentials are mounted read-only and never baked into the image.

---

## Deployment keys

Access is controlled by RSA-signed deployment keys. Each key encodes:

- The organisation name
- Issue date
- Optional expiry date

**To request a key**, contact the administrator with your organisation name and preferred expiry period (e.g. 365 days, or no expiry).

**Keys are per-organisation.** If you are deploying for multiple teams, request a separate key for each.

---

## User management

Users are managed in `auth/credentials.yaml` — a local file that never leaves the deployment machine. There is no central user database.

**To add a user:**

1. Generate a bcrypt hash for their password (see step 4 above)
2. Add an entry under `credentials.usernames` in `credentials.yaml`
3. Restart the app (or the Docker container)

**To remove a user:** delete their entry from `credentials.yaml` and restart.

**To change a password:** replace the `password` hash for that user and restart.

---

## File structure

```
app.py                        # Entry point
auth/
  key_validator.py            # Deployment key verification
  keygen.py                   # Key generation script (administrator only)
  public_key.pem              # RSA public key (safe to distribute)
  credentials.yaml.example    # Template — copy to credentials.yaml
config/
demand/
models/
optimisation/
persistence/
planning/
roster/
simulation/
supply/
tests/
ui/
requirements.txt
Dockerfile
docker-compose.yml
.env.example
```

**Files that must not be committed:**

| File | Reason |
|---|---|
| `.env` | Contains deployment key |
| `auth/credentials.yaml` | Contains bcrypt-hashed passwords |
| `auth/private_key.pem` | RSA private key (administrator only) |
| `state/` | Local persistent state |

All of these are listed in `.gitignore`.

---

## Running tests

```bash
pytest tests/ -v
```

All 112 tests should pass. The Parquet roundtrip test in `test_state_manager.py` is skipped automatically if `pyarrow` is not installed (it is always available when installed from `requirements.txt`).

---

## Updating credentials without restarting

If using Docker, you can update `auth/credentials.yaml` on the host and ask Streamlit to reload by navigating to the running app and pressing `R` (rerun) — the YAML is re-read on every login attempt so no container restart is required for credential changes.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full development plan. Upcoming phases include demand forecasting from historical data, PDF report export, and multi-queue / multi-skill modelling.
