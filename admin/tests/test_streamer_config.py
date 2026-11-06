"""
Contract tests for the shipped streamer-node config
(``config/streamer/application.yml``) — Phase 1 of
``docs/DESIGN-two-node-split.md``.

The streamer variant is *derived* from the all-in-one config: everything
except the design deltas (D1/D2/D4) is meant to stay identical, because
encoded tracks are only portable between nodes running the same plugin
versions (D3). These tests pin both halves of that statement — the
deltas are exactly the design's, and the shared parts cannot drift.
"""
from pathlib import Path

from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_CONFIG = REPO_ROOT / "config" / "application.yml"
STREAMER_CONFIG = REPO_ROOT / "config" / "streamer" / "application.yml"


def _load(path: Path) -> dict:
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        return yaml.load(f)


def _base() -> dict:
    return _load(BASE_CONFIG)


def _streamer() -> dict:
    assert STREAMER_CONFIG.exists(), f"streamer config missing at {STREAMER_CONFIG}"
    return _load(STREAMER_CONFIG)


def test_streamer_plugin_versions_match_base():
    """D3: same Lavalink plugin dependencies, byte for byte."""
    assert _streamer()["lavalink"]["plugins"] == _base()["lavalink"]["plugins"]


def test_streamer_clients_are_tv_only():
    """D4: no fallback clients — a TV failure is a hard failure."""
    assert _streamer()["plugins"]["youtube"]["clients"] == ["TV"]


def test_streamer_search_is_disabled():
    assert _streamer()["plugins"]["youtube"]["allowSearch"] is False


def test_streamer_oauth_enabled_and_token_path_present():
    """D1: the account credential lives on this node; the admin's OAuth
    flow writes plugins.youtube.oauth.refreshToken, so the key must
    exist (same contract as the base config)."""
    oauth = _streamer()["plugins"]["youtube"]["oauth"]
    assert oauth["enabled"] is True
    assert "refreshToken" in oauth


def test_streamer_has_no_pot_block():
    """D2: PoToken is resolver-only kit. The plugin's loader is
    null-safe for a missing pot block (verified in 1.18.2 source:
    YoutubePluginLoader checks `pot != null` before applying)."""
    assert "pot" not in _streamer()["plugins"]["youtube"]


def test_streamer_remote_cipher_configured():
    """Playback makes player requests, so the cipher must be wired
    exactly as on the base config."""
    assert (
        _streamer()["plugins"]["youtube"]["remoteCipher"]
        == _base()["plugins"]["youtube"]["remoteCipher"]
    )


def test_streamer_keeps_decode_surface_identical():
    """Encoded tracks from any source must decode here: built-in source
    toggles and the LavaSrc provider chain stay in lockstep with base."""
    assert _streamer()["lavalink"]["server"]["sources"] == _base()["lavalink"]["server"]["sources"]
    assert _streamer()["plugins"]["lavasrc"] == _base()["plugins"]["lavasrc"]


def test_streamer_has_no_route_planner():
    """Rotation is the resolver's mechanism; the streamer keeps one IP."""
    assert "routePlanner" not in _streamer().get("metrics", {})
