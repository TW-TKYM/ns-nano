from sqlalchemy.engine import make_url


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]

    url = make_url(database_url)
    if url.get_backend_name() == "postgresql":
        url = url.set(drivername="postgresql+psycopg2")
    return url.render_as_string(hide_password=False)
