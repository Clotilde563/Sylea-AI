"""Tests pour api.feature_flags."""

from __future__ import annotations

import time

import pytest

import api.feature_flags as ff


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.delenv("SYLEA_FF_BACKEND", raising=False)
    ff.reset_backend()


@pytest.fixture
def yaml_file(tmp_path, monkeypatch):
    """Crée un fichier YAML temporaire de flags + pointe le backend dessus."""
    path = tmp_path / "flags.yaml"
    monkeypatch.setenv("SYLEA_FF_LOCAL_PATH", str(path))
    monkeypatch.setenv("SYLEA_FF_BACKEND", "local")
    ff.reset_backend()
    return path


def write_yaml(path, content):
    path.write_text(content, encoding="utf-8")


def test_default_off_when_no_file(monkeypatch):
    monkeypatch.setenv("SYLEA_FF_LOCAL_PATH", "/nonexistent/path.yaml")
    ff.reset_backend()
    assert ff.is_enabled("foo", user_id="u1") is False
    assert ff.get_variant("foo", user_id="u1", default="control") == "control"


def test_basic_on_for_all(yaml_file):
    write_yaml(yaml_file, """
features:
  myflag:
    default: on
""")
    assert ff.is_enabled("myflag", user_id="u1") is True
    assert ff.is_enabled("myflag", user_id="u999") is True


def test_default_off(yaml_file):
    write_yaml(yaml_file, """
features:
  myflag:
    default: off
""")
    assert ff.is_enabled("myflag", user_id="u1") is False


def test_user_id_whitelist(yaml_file):
    write_yaml(yaml_file, """
features:
  myflag:
    default: off
    rules:
      - user_id_in: [alice, bob]
        variant: on
""")
    assert ff.is_enabled("myflag", user_id="alice") is True
    assert ff.is_enabled("myflag", user_id="bob") is True
    assert ff.is_enabled("myflag", user_id="charlie") is False


def test_tier_targeting(yaml_file):
    write_yaml(yaml_file, """
features:
  pro_feature:
    default: off
    rules:
      - user_tier_in: [advanced, enterprise]
        variant: on
""")
    assert ff.is_enabled("pro_feature", user_id="u1",
                         user_attrs={"tier": "free"}) is False
    assert ff.is_enabled("pro_feature", user_id="u1",
                         user_attrs={"tier": "advanced"}) is True
    assert ff.is_enabled("pro_feature", user_id="u1",
                         user_attrs={"tier": "enterprise"}) is True


def test_rollout_percentage_deterministic(yaml_file):
    write_yaml(yaml_file, """
features:
  canary:
    default: off
    rules:
      - rollout_pct: 50
        variant: on
""")
    # Avec une rollout 50%, environ moitié des users en bucket
    enabled_count = 0
    for i in range(200):
        if ff.is_enabled("canary", user_id=f"user-{i}"):
            enabled_count += 1
    # Toléré : 30-70% (variabilité hash)
    assert 80 <= enabled_count <= 120


def test_rollout_is_stable_per_user(yaml_file):
    """Le même user doit TOUJOURS être dans le même bucket."""
    write_yaml(yaml_file, """
features:
  rollout_test:
    default: off
    rules:
      - rollout_pct: 50
        variant: on
""")
    decisions = [ff.is_enabled("rollout_test", user_id="alice") for _ in range(10)]
    assert len(set(decisions)) == 1


def test_time_based_activation(yaml_file):
    future = time.time() + 3600
    write_yaml(yaml_file, f"""
features:
  upcoming:
    default: off
    rules:
      - start_at: {future}
        variant: on
""")
    # Pas encore active
    assert ff.is_enabled("upcoming", user_id="u1") is False


def test_time_based_already_active(yaml_file):
    past = time.time() - 3600
    write_yaml(yaml_file, f"""
features:
  active_now:
    default: off
    rules:
      - start_at: {past}
        variant: on
""")
    assert ff.is_enabled("active_now", user_id="u1") is True


def test_first_matching_rule_wins(yaml_file):
    write_yaml(yaml_file, """
features:
  multi:
    default: off
    rules:
      - user_id_in: [alice]
        variant: special
      - rollout_pct: 100
        variant: on
""")
    assert ff.get_variant("multi", user_id="alice") == "special"
    assert ff.get_variant("multi", user_id="bob") == "on"


def test_country_targeting(yaml_file):
    write_yaml(yaml_file, """
features:
  fr_only:
    default: off
    rules:
      - country_in: [FR, BE]
        variant: on
""")
    assert ff.is_enabled("fr_only", user_id="u1",
                         user_attrs={"country": "FR"}) is True
    assert ff.is_enabled("fr_only", user_id="u1",
                         user_attrs={"country": "US"}) is False


def test_list_features(yaml_file):
    write_yaml(yaml_file, """
features:
  flag_a: { default: on }
  flag_b: { default: off }
  flag_c: { default: on }
""")
    flags = ff.list_features()
    assert set(flags) == {"flag_a", "flag_b", "flag_c"}


def test_hot_reload(yaml_file):
    write_yaml(yaml_file, """
features:
  flag1: { default: off }
""")
    assert ff.is_enabled("flag1") is False

    # Modifie le fichier + force reload
    time.sleep(0.01)
    write_yaml(yaml_file, """
features:
  flag1: { default: on }
""")
    ff.reload()
    assert ff.is_enabled("flag1") is True


def test_bucketing_distribution_uniform():
    """Vérifie que la distribution des buckets est ~ uniforme."""
    from api.feature_flags import _bucket_user
    buckets = [_bucket_user("test_feature", f"u{i}") for i in range(10000)]
    # Decile counts
    deciles = [0] * 10
    for b in buckets:
        deciles[min(int(b // 10), 9)] += 1
    # Chaque décile devrait contenir ~1000 ± 200 users
    for count in deciles:
        assert 700 < count < 1300, f"deciles distribution skewed: {deciles}"
