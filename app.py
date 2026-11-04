import math
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from db_utils import normalize_database_url

_engine = None
DEFAULT_RADIUS_MM = 10.0
MAX_RADIUS_MM = 100.0
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000


class DatabaseConfigurationError(RuntimeError):
    pass


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        raise DatabaseConfigurationError(
            "Set DB_URL or DATABASE_URL to the PostgreSQL connection URL."
        )
    db_url = normalize_database_url(db_url)
    _engine = create_engine(db_url, pool_pre_ping=True)
    return _engine


def parse_coordinates(value):
    try:
        coordinates = tuple(float(part) for part in value.split("_"))
    except ValueError as exc:
        raise ValueError("Coordinates must use the x_y_z format.") from exc

    if len(coordinates) != 3 or not all(map(math.isfinite, coordinates)):
        raise ValueError("Coordinates must contain three finite numbers in x_y_z format.")
    return coordinates


def parse_radius():
    try:
        radius = float(request.args.get("radius_mm", DEFAULT_RADIUS_MM))
    except ValueError as exc:
        raise ValueError("radius_mm must be a number from 0 to 100.") from exc
    if not math.isfinite(radius) or not 0 <= radius <= MAX_RADIUS_MM:
        raise ValueError("radius_mm must be a number from 0 to 100.")
    return radius


def parse_pagination():
    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
        offset = int(request.args.get("offset", 0))
    except ValueError as exc:
        raise ValueError("limit and offset must be integers.") from exc
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise ValueError(f"limit must be 1-{MAX_LIMIT} and offset must be 0 or greater.")
    return limit, offset


def normalize_term(term):
    normalized = " ".join(term.strip().replace("_", " ").casefold().split())
    if not normalized:
        raise ValueError("Terms cannot be empty.")
    return normalized


def get_studies(query, params, limit, offset):
    paged_query = text(
        f"""
        SELECT study_id, COUNT(*) OVER () AS total
        FROM ({query}) AS matches
        ORDER BY study_id
        LIMIT :limit OFFSET :offset
        """
    )
    query_params = {**params, "limit": limit, "offset": offset}

    with get_engine().connect() as conn:
        rows = conn.execute(paged_query, query_params).mappings().all()
        if rows:
            total = rows[0]["total"]
            studies = [row["study_id"] for row in rows]
        else:
            total = conn.execute(
                text(f"SELECT COUNT(*) FROM ({query}) AS matches"), params
            ).scalar_one()
            studies = []

    return {
        "count": total,
        "limit": limit,
        "offset": offset,
        "studies": studies,
    }


def term_studies_query(term_a, term_b=None):
    query = """
        SELECT DISTINCT a.study_id
        FROM ns.annotations_terms AS a
        WHERE (
            a.term = :term_a
            OR a.term = 'terms_abstract_tfidf__' || :term_a
        )
    """
    if term_b is not None:
        query += """
            AND NOT EXISTS (
                SELECT 1
                FROM ns.annotations_terms AS b
                WHERE b.study_id = a.study_id
                  AND (
                      b.term = :term_b
                      OR b.term = 'terms_abstract_tfidf__' || :term_b
                  )
            )
        """
    return query


def nearby_studies_query(prefix, coords, radius):
    x, y, z = coords
    return f"""
        SELECT DISTINCT c.study_id
        FROM ns.coordinates AS c
        WHERE ST_DWithin(
                  c.geom,
                  ST_SetSRID(ST_MakePoint(:{prefix}_x, :{prefix}_y, :{prefix}_z), 4326),
                  :radius
              )
          AND POWER(ST_X(c.geom) - :{prefix}_x, 2)
              + POWER(ST_Y(c.geom) - :{prefix}_y, 2)
              + POWER(ST_Z(c.geom) - :{prefix}_z, 2) <= :radius_squared
    """, {
        f"{prefix}_x": x,
        f"{prefix}_y": y,
        f"{prefix}_z": z,
        "radius": radius,
        "radius_squared": radius ** 2,
    }


def location_studies_query(coords_a, coords_b, radius):
    query_a, params_a = nearby_studies_query("a", coords_a, radius)
    query_b, params_b = nearby_studies_query("b", coords_b, radius)
    query = f"""
        SELECT a.study_id
        FROM ({query_a}) AS a
        WHERE NOT EXISTS (
            SELECT 1 FROM ({query_b}) AS b WHERE b.study_id = a.study_id
        )
    """
    return query, {**params_a, **params_b}


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ValueError)
    def handle_bad_request(error):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(DatabaseConfigurationError)
    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error):
        app.logger.exception("Database request failed")
        return jsonify({"error": "Database is not configured or is unavailable."}), 503

    @app.get("/", endpoint="health")
    def health():
        return "<p>Server working!</p>"

    @app.get("/img", endpoint="show_img")
    def show_img():
        return send_file(Path(__file__).with_name("amygdala.gif"), mimetype="image/gif")

    @app.get("/terms/<term>/studies", endpoint="terms_studies")
    def get_studies_by_term(term):
        limit, offset = parse_pagination()
        normalized_term = normalize_term(term)
        result = get_studies(
            term_studies_query(normalized_term),
            {"term_a": normalized_term},
            limit,
            offset,
        )
        result["term"] = normalized_term
        return jsonify(result)

    @app.get("/locations/<coords>/studies", endpoint="locations_studies")
    def get_studies_by_coordinates(coords):
        point = parse_coordinates(coords)
        radius = parse_radius()
        limit, offset = parse_pagination()
        query, params = nearby_studies_query("a", point, radius)
        result = get_studies(query, params, limit, offset)
        result.update({"coordinates": point, "radius_mm": radius})
        return jsonify(result)

    @app.get("/dissociate/terms/<term_a>/<term_b>")
    def dissociate_by_terms(term_a, term_b):
        limit, offset = parse_pagination()
        term_a = normalize_term(term_a)
        term_b = normalize_term(term_b)
        if term_a == term_b:
            raise ValueError("The two terms must be different.")
        result = get_studies(
            term_studies_query(term_a, term_b),
            {"term_a": term_a, "term_b": term_b},
            limit,
            offset,
        )
        result["terms"] = {"a": term_a, "b": term_b}
        return jsonify(result)

    @app.get("/dissociate/locations/<coords_a>/<coords_b>")
    def dissociate_by_coordinates(coords_a, coords_b):
        point_a = parse_coordinates(coords_a)
        point_b = parse_coordinates(coords_b)
        radius = parse_radius()
        limit, offset = parse_pagination()
        query, params = location_studies_query(point_a, point_b, radius)
        result = get_studies(query, params, limit, offset)
        result.update({
            "coordinates": {"a": point_a, "b": point_b},
            "radius_mm": radius,
        })
        return jsonify(result)

    @app.get("/test_db", endpoint="test_db")
    def test_db():
        eng = get_engine()
        with eng.begin() as conn:
            conn.execute(text("SET search_path TO ns, public;"))
            payload = {
                "ok": True,
                "dialect": eng.dialect.name,
                "version": conn.exec_driver_sql("SELECT version()").scalar(),
                "coordinates_count": conn.execute(
                    text("SELECT COUNT(*) FROM ns.coordinates")
                ).scalar(),
                "metadata_count": conn.execute(
                    text("SELECT COUNT(*) FROM ns.metadata")
                ).scalar(),
                "annotations_terms_count": conn.execute(
                    text("SELECT COUNT(*) FROM ns.annotations_terms")
                ).scalar(),
            }
        return jsonify(payload)

    return app


app = create_app()
