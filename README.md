# Berza Koktela

Dynamic pricing system for cocktails - a bar exchange where prices fluctuate based on demand.

## Setup

### Requirements

- Python 3.8+
- `uv` (package manager) - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

### Installation & Running

**First time setup:**

```bash
# 1. Clone the repository
git clone <repository>
cd Berza_Shot

# 2. Create virtual environment
uv venv

# 3. Activate it
source .venv/bin/activate  # Mac/Linux
# OR on Windows:
.venv\Scripts\activate

# 4. Install dependencies
uv sync

# 5. Run the application
uv run python Berza_Koktela.py
```

**Subsequent runs** (after first setup):

```bash
source .venv/bin/activate  # Mac/Linux or .venv\Scripts\activate on Windows
uv run python Berza_Koktela.py
```

### Database

- **First run**: Database is automatically created with 20 default cocktails in `instance/berza_koktela.db`
- **Subsequent runs**: Existing database is used - prices and transactions persist
- **To reset data**: Delete the database file:
  ```bash
  rm instance/berza_koktela.db
  ```
  Then restart the app - it will create a fresh database with default cocktails

## Usage

- **Order Entry** → http://localhost:5000/unos_narudzbe
- **Live Display** → http://localhost:5000/tv
- **Dashboard** → http://localhost:5000/dashboard
- **Transactions** → http://localhost:5000/transakcije

## How It Works

### Dynamic Pricing Algorithm

Prices update automatically every 30 seconds based on sales volume:

- **High demand** (units sold > 0) → Price increases by 1% per unit sold
- **Low demand** (no sales) → Price decreases by 2%
- **Price bounds** → Always constrained to 70% - 130% of the base price

Example:

- Base price: 650 RSD
- Min limit: 455 RSD (70%)
- Max limit: 845 RSD (130%)
- If 2 units sold: 650 × 1.02 = 663 RSD ↑
- If 0 units sold: 650 × 0.98 = 637 RSD ↓

### Default Cocktails (20 total)

All prices in RSD:

| Cocktail            | Base Price | Min | Max |
| ------------------- | ---------- | --- | --- |
| DEVILS ICE TEA      | 690        | 483 | 897 |
| LONG ISLAND ICE TEA | 670        | 469 | 871 |
| BEAST               | 690        | 483 | 897 |
| STOPER              | 666        | 466 | 866 |
| SHOOTIRANJE         | 666        | 466 | 866 |
| ADIOS MOTHERFUCKER  | 666        | 466 | 866 |
| TEQUILA SUNRISE     | 630        | 441 | 819 |
| SEX ON THE BEACH    | 630        | 441 | 819 |
| JAPANESE SLIPPER    | 630        | 441 | 819 |
| BAHAMA MAMA         | 630        | 441 | 819 |
| VISKI SOUR          | 630        | 441 | 819 |
| BLACK SABATH        | 630        | 441 | 819 |
| LA ICE TEA          | 650        | 455 | 845 |
| BLUE FROG           | 650        | 455 | 845 |
| HERO                | 650        | 455 | 845 |
| MAI TAI             | 640        | 448 | 832 |
| BLUE LAGOON         | 610        | 427 | 793 |
| COSMOPOLITAN        | 580        | 406 | 754 |
| CUBA LIBRE          | 580        | 406 | 754 |
| MARGARITA KOKTEL    | 580        | 406 | 754 |
