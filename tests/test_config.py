import os

import pytest

from worklog.config import ConfigError, load_config


def test_missing_file_uses_defaults(tmp_path):
    config = load_config(tmp_path / "none.toml")
    assert config.gap_minutes == 15 and config.timezone is None and config.config_path is None


def test_values_are_expanded(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'gap_minutes = 10\n[aliases]\n"~/Old/*" = "~/New/*"\n[clients]\n"A" = "~/New/a"\n', encoding="utf-8"
    )
    config = load_config(path)
    home = os.path.expanduser("~")
    assert config.gap_minutes == 10
    assert config.aliases == [(f"{home}/Old/*", f"{home}/New/*")]
    assert config.clients == [("A", [f"{home}/New/a"])]


@pytest.mark.parametrize("body", ['timezone = "Mars/Base"', "gap_minutes = -1", "gap_minutes = ["])
def test_invalid_config(tmp_path, body):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
