import sqlite3

import pytest

from tollroute import cost


@pytest.fixture
def conn():
    from tollroute.etl.load import SCHEMA_PATH

    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA_PATH.read_text())
    yield c
    c.close()


def test_seed_class_config_inserts_defaults(conn):
    inserted = cost.seed_class_config(conn)
    assert inserted == len(cost.DEFAULT_CLASS_CONFIG)

    (count,) = conn.execute("SELECT COUNT(*) FROM class_config").fetchone()
    assert count == len(cost.DEFAULT_CLASS_CONFIG)


def test_seed_class_config_is_idempotent(conn):
    cost.seed_class_config(conn)
    second = cost.seed_class_config(conn)
    assert second == 0

    (count,) = conn.execute("SELECT COUNT(*) FROM class_config").fetchone()
    assert count == len(cost.DEFAULT_CLASS_CONFIG)


def test_seed_class_config_never_overwrites_existing_rows(conn):
    conn.execute(
        "INSERT INTO class_config (vehicle_class, running_cost_per_km, "
        "value_of_time_eur_per_hour, is_conjecture) VALUES (1, 0.99, 999.0, 0)"
    )
    conn.commit()

    cost.seed_class_config(conn)

    row = conn.execute(
        "SELECT running_cost_per_km, value_of_time_eur_per_hour, is_conjecture "
        "FROM class_config WHERE vehicle_class = 1"
    ).fetchone()
    assert row == (0.99, 999.0, 0)


def test_load_class_config_round_trips(conn):
    cost.seed_class_config(conn)
    config = cost.load_class_config(conn)

    assert set(config) == set(cost.DEFAULT_CLASS_CONFIG)
    for vehicle_class, (cost_km, vot) in cost.DEFAULT_CLASS_CONFIG.items():
        entry = config[vehicle_class]
        assert entry.vehicle_class == vehicle_class
        assert entry.running_cost_per_km == pytest.approx(cost_km)
        assert entry.value_of_time_eur_per_hour == pytest.approx(vot)
        assert entry.is_conjecture is True


def test_load_class_config_raises_on_empty_table(conn):
    with pytest.raises(RuntimeError):
        cost.load_class_config(conn)


def test_class4_running_cost_and_vot_exceed_class1():
    # Spec anchors (iterative-tumbling-lecun.md Phase 4a): HGVs cost more
    # per km and carry a higher value of time than light vehicles.
    c1_km, c1_vot = cost.DEFAULT_CLASS_CONFIG[1]
    c4_km, c4_vot = cost.DEFAULT_CLASS_CONFIG[4]
    assert c4_km > c1_km
    assert c4_vot > c1_vot


@pytest.mark.parametrize(
    "toll,distance_m,duration_s,cost_per_km,vot,expected",
    [
        (0.0, 0.0, 0.0, 0.15, 12.0, 0.0),
        (10.0, 0.0, 0.0, 0.15, 12.0, 10.0),
        (0.0, 100_000.0, 0.0, 0.15, 12.0, 15.0),
        (0.0, 0.0, 3600.0, 0.15, 12.0, 12.0),
        (14.1, 200_000.0, 9000.0, 0.15, 12.0, 14.1 + 30.0 + 30.0),
    ],
)
def test_generalised_cost_formula(toll, distance_m, duration_s, cost_per_km, vot, expected):
    assert cost.generalised_cost(toll, distance_m, duration_s, cost_per_km, vot) == pytest.approx(
        expected
    )
