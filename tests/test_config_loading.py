import os

from mofang_mcp.config import Settings


def test_settings_load_from_yaml_config_file(tmp_path) -> None:
    config_path = tmp_path / "server.yaml"
    config_path.write_text(
        "\n".join(
            [
                "base_url: https://example.com",
                "manifest_path: data/api_manifest.json",
                "cache_dir: /tmp/custom-cache",
                "timeout_seconds: 12",
                "http_host: 127.0.0.1",
                "http_port: 9010",
                "http_path: /mcp/custom/stream",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.from_file_or_env(str(config_path))

    assert settings.base_url == "https://example.com"
    assert str(settings.manifest_path).endswith("data/api_manifest.json")
    assert str(settings.cache_dir) == "/tmp/custom-cache"
    assert settings.timeout_seconds == 12
    assert settings.http_host == "127.0.0.1"
    assert settings.http_port == 9010
    assert settings.http_path == "/mcp/custom/stream"


def test_settings_without_config_still_uses_env(monkeypatch) -> None:
    monkeypatch.setenv("MOFANG_MCP_HTTP_HOST", "127.0.0.2")
    monkeypatch.setenv("MOFANG_MCP_HTTP_PORT", "9020")
    monkeypatch.setenv("MOFANG_MCP_HTTP_PATH", "/mcp/env/stream")

    settings = Settings.from_file_or_env(None)

    assert settings.http_host == "127.0.0.2"
    assert settings.http_port == 9020
    assert settings.http_path == "/mcp/env/stream"


def test_settings_config_overrides_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MOFANG_MCP_HTTP_HOST", "127.0.0.9")
    monkeypatch.setenv("MOFANG_MCP_HTTP_PORT", "9999")
    monkeypatch.setenv("MOFANG_MCP_HTTP_PATH", "/mcp/env/stream")

    config_path = tmp_path / "server.yaml"
    config_path.write_text(
        "\n".join(
            [
                "http_host: 127.0.0.7",
                "http_port: 9777",
                "http_path: /mcp/file/stream",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.from_file_or_env(str(config_path))

    assert settings.http_host == "127.0.0.7"
    assert settings.http_port == 9777
    assert settings.http_path == "/mcp/file/stream"
