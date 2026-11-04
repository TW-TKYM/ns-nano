# Neurosynth Backend

A lightweight Flask backend that exposes **functional dissociation** endpoints on top of a Neurosynth-backed PostgreSQL database.

The service provides two APIs that return studies mentioning one concept/coordinate **but not** the other (A \ B). You can also query the opposite direction (B \ A).

---

## Table of Contents

- [Endpoints](#endpoints)
  - [Dissociate by terms](#dissociate-by-terms)
  - [Dissociate by MNI coordinates](#dissociate-by-mni-coordinates)
- [Quick Start](#quick-start)
  - [1) Provision PostgreSQL](#1-provision-postgresql)
  - [2) Verify the connection](#2-verify-the-connection)
  - [3) Populate the database](#3-populate-the-database)
  - [4) Run the Flask service](#4-run-the-flask-service)
  - [5) Smoke tests](#5-smoke-tests)
- [Environment Variables](#environment-variables)
- [Example Requests](#example-requests)
- [Requirements](#requirements)
- [Notes](#notes)
- [License](#license)

---

## Endpoints

### Dissociate by terms

```
GET /dissociate/terms/<term_a>/<term_b>
```

Returns unique `study_id` values with **`term_a`** but no **`term_b`**.
Term matching is case-insensitive; spaces and underscores are treated alike.
The loader removes the source column prefix (for example,
`terms_abstract_tfidf__`) so stored terms can be queried by their actual names.
Results are paginated with `limit` (default 1,000; maximum 5,000) and `offset`
(default 0). The JSON response contains `count`, `limit`, `offset`, `studies`,
and the normalized input terms.

**Examples**

```
/dissociate/terms/posterior_cingulate/ventromedial_prefrontal
/dissociate/terms/ventromedial_prefrontal/posterior_cingulate
```

---

### Dissociate by MNI coordinates

```
GET /dissociate/locations/<x1_y1_z1>/<x2_y2_z2>
```

Coordinates are passed as `x_y_z` (underscores, not commas).  
Returns unique `study_id` values with a coordinate within the 3D radius of
**`[x1, y1, z1]`** but no coordinate within the radius of **`[x2, y2, z2]`**.
Coordinates are compared in the source coordinate units (MNI millimeters).
The radius defaults to 10 mm and can be set with `?radius_mm=...` (0–100).
Results use the same `limit` and `offset` pagination as the term endpoint.

**Default Mode Network test case**

```
/dissociate/locations/0_-52_26/-2_50_-6
/dissociate/locations/-2_50_-6/0_-52_26
```

> Tip: You may design a single endpoint that returns **both directions** in one response (A–B **and** B–A) if that better suits your client.

The current endpoint returns A–B. Reverse the two coordinates in a second
request to get B–A.

---

## Quick Start

Install the backend and database-loader dependencies:

```bash
pip install -r requirements.txt
```

### 1) Provision PostgreSQL

Create a PostgreSQL database (e.g., on Render).

### 2) Verify the connection

```bash
python check_db.py --url "postgresql://<USER>:<PASSWORD>@<HOST>:5432/<DBNAME>"
```

### 3) Populate the database

```bash
python create_db.py --url "postgresql://<USER>:<PASSWORD>@<HOST>:5432/<DBNAME>"
```

### 4) Deploy the Flask service

Push the contents of this folder to a GitHub repository, then create a new
Blueprint in Render and select that repository. Render reads `render.yaml` to
build and start the Flask service. In the service's environment settings, set
`DB_URL` to a PostgreSQL connection string reachable from Render. Do not use
`127.0.0.1` or `localhost`: those addresses refer to the Render service itself,
not your computer.

The database must have PostGIS available. A local PostgreSQL database is not
automatically reachable from Render; use a hosted PostgreSQL service that
supports PostGIS and populate it with the included Parquet data before testing
the query endpoints. Keep database credentials in Render's environment
settings, never in the repository.

If deploying without the Blueprint, configure a Python web service with this
build command and start command:

```text
Build: pip install -r requirements.txt
Start: gunicorn app:app --bind 0.0.0.0:$PORT
```

### 5) Smoke tests

After deployment, check the basic endpoints:

- Health check: `https://<your-app>.onrender.com/`
- Images: `https://<your-app>.onrender.com/img`
- DB connectivity: `https://<your-app>.onrender.com/test_db`
- Term dissociation: `https://<your-app>.onrender.com/dissociate/terms/posterior_cingulate/ventromedial_prefrontal`
- Coordinate dissociation: `https://<your-app>.onrender.com/dissociate/locations/0_-52_26/-2_50_-6?radius_mm=10`

---

## Environment Variables

- **`DB_URL`** – Full PostgreSQL connection string used by the app.  
  Example: `postgresql://<USER>:<PASSWORD>@<HOST>:5432/<DBNAME>`

> **Security note:** Never commit real credentials to version control. Use environment variables or your hosting provider’s secret manager.

---

## Example Requests

**By terms**

```bash
curl https://<your-app>.onrender.com/dissociate/terms/posterior_cingulate/ventromedial_prefrontal
curl https://<your-app>.onrender.com/dissociate/terms/ventromedial_prefrontal/posterior_cingulate
```

**By coordinates**

```bash
curl "https://<your-app>.onrender.com/dissociate/locations/0_-52_26/-2_50_-6?radius_mm=10"
curl "https://<your-app>.onrender.com/dissociate/locations/-2_50_-6/0_-52_26?radius_mm=10"
```

---

## Requirements

- Python 3.10+
- PostgreSQL 12+
- Python dependencies (typical):
  - `Flask`
  - `SQLAlchemy`
  - PostgreSQL driver (e.g., `psycopg2-binary`)
  - Production WSGI server (e.g., `gunicorn`)
  - `pandas`, `NumPy`, and `PyArrow` for loading the included Parquet data

---

## Notes

- Path parameters use underscores (`_`) between coordinates: `x_y_z`.
- The coordinate query uses a 3D Euclidean distance, not just an x/y match.
- Responses contain a `studies` array of study IDs and a total `count`; use `limit` and `offset` for paging.
- The term/coordinate pairs above illustrate a **Default Mode Network** dissociation example. Adjust for your analysis.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
