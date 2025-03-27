from unittest.mock import MagicMock, call, patch
import os
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from traefik_validator import settings
from traefik_validator.utils import SchemaDownloader, Validator


class TestValidator:

    @pytest.fixture(autouse=True)
    def mock_settings(self):
        settings.STATIC_CONFS_SCHEMA_URL = "https://static.com"
        settings.DYNAMIC_CONFS_SCHEMA_URL = "https://dynamic.com"

    @pytest.fixture(autouse=True)
    def mock_schema_downloader(self, mocker):
        # Updated mock schema to match Traefik v3 structure with $defs instead of definitions
        mock_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "$defs": {  # Changed from definitions to $defs for v3
                "httpRouter": {
                    "type": "object",
                    "description": "",
                    "properties": {
                        "rule": {
                            "type": "string",
                            "description": ""
                        },
                    },
                    "additionalProperties": False,
                    "required": [
                        "rule",
                    ]
                },
            },
            "properties": {
                "http": {
                    "type": "object",
                    "properties": {
                        "routers": {
                            "type": "object",
                            "additionalProperties": {
                                "$ref": "#/$defs/httpRouter"  # Updated reference from #/definitions to #/$defs
                            }
                        }
                    }
                }
            }
        }
        mocker.patch("traefik_validator.utils.SchemaDownloader.download_from_url", return_value=mock_schema)
        # Mock the cache methods
        mocker.patch("traefik_validator.utils.SchemaDownloader._is_cache_valid", return_value=False)
        mocker.patch("traefik_validator.utils.SchemaDownloader._get_cache_path", return_value=Path("/tmp/cache.json"))
        mocker.patch("json.dump")
        mocker.patch("json.load", return_value=mock_schema)
        mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("os.makedirs")

    @pytest.fixture(autouse=True)
    def mock_load_yaml(self, mocker):
        mock_yaml = {
            "not_test": 2
        }
        mocker.patch("traefik_validator.utils.Validator.load_yaml", return_value=mock_yaml)

    def test_validator_without_any_files_raise_value_error(self):
        with pytest.raises(ValueError):
            Validator()

    def test_validator_with_both_static_and_dynamic_file_calls_download_twice(self):
        validator = Validator(MagicMock(), MagicMock())
        with patch("builtins.print"):  # Suppress print output during test
            validator.validate()
        assert SchemaDownloader.download_from_url.call_count == 2
        SchemaDownloader.download_from_url.assert_has_calls(
            [call(url="https://static.com"), call(url="https://dynamic.com")]
        )

    def test_validator_with_static_file_calls_download_one(self):
        validator = Validator(static_conf_file=MagicMock())
        with patch("builtins.print"):  # Suppress print output during test
            validator.validate()
        assert SchemaDownloader.download_from_url.call_count == 1
        SchemaDownloader.download_from_url.assert_has_calls(
            [call(url="https://static.com")]
        )

    def test_validator_with_dynamic_file_calls_download_one(self):
        validator = Validator(dynamic_conf_file=MagicMock())
        with patch("builtins.print"):  # Suppress print output during test
            validator.validate()
        assert SchemaDownloader.download_from_url.call_count == 1
        SchemaDownloader.download_from_url.assert_has_calls(
            [call(url="https://dynamic.com")]
        )

    def test_validate_with_invalid_data_raise_error(self, mocker):
        mock_yaml = {
            'http': {
                'routers': {
                    'router_test': {
                        'test': ''
                    }
                }
            }
        }
        mocker.patch("traefik_validator.utils.Validator.load_yaml", return_value=mock_yaml)
        validator = Validator(dynamic_conf_file=MagicMock())
        with pytest.raises(ValidationError):
            with patch("builtins.print"):  # Suppress print output during test
                validator.validate()

    def test_validate_with_valid_data_no_return(self, mocker):
        mock_yaml = {
            'http': {
                'routers': {
                    'router_test': {
                        'rule': 'Host(`test.com`) || Host(`www.test.com`)'
                    }
                }
            }
        }
        mocker.patch("traefik_validator.utils.Validator.load_yaml", return_value=mock_yaml)
        validator = Validator(dynamic_conf_file=MagicMock())
        with patch("builtins.print"):  # Suppress print output during test
            res = validator.validate()
        assert res is None

    def test_offline_mode_uses_cache(self, mocker):
        # Set up mocks
        is_cache_valid_mock = mocker.patch("traefik_validator.utils.SchemaDownloader._is_cache_valid", return_value=True)
        download_from_url_mock = mocker.patch("traefik_validator.utils.SchemaDownloader.download_from_url")
        json_load_mock = mocker.patch("json.load", return_value={})
        
        # Create validator in offline mode
        validator = Validator(dynamic_conf_file=MagicMock(), offline=True)
        
        # Call validate
        with patch("builtins.print"):  # Suppress print output during test
            validator.validate()
        
        # Check that download was not called and cache was used
        assert is_cache_valid_mock.called
        assert json_load_mock.called
        download_from_url_mock.assert_not_called()


class TestSchemaDownloader:

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        # Mock os.makedirs to avoid creating directories
        mocker.patch("os.makedirs")
        
        # Mock the cache path
        mocker.patch("traefik_validator.utils.SchemaDownloader.CACHE_DIR", Path("/tmp/test-cache"))
        
        # Mock time for cache validation tests
        mocker.patch("time.time", return_value=1000)

    def test_get_cache_path(self):
        downloader = SchemaDownloader()
        cache_path = downloader._get_cache_path("https://example.com/schema.json")
        assert isinstance(cache_path, Path)
        assert "schema.json" not in str(cache_path)  # Should be hashed
        assert str(cache_path).endswith(".json")

    def test_is_cache_valid_when_file_doesnt_exist(self, mocker):
        downloader = SchemaDownloader()
        mocker.patch("pathlib.Path.exists", return_value=False)
        assert not downloader._is_cache_valid(Path("/tmp/nonexistent"))

    def test_is_cache_valid_when_file_is_recent(self, mocker):
        downloader = SchemaDownloader()
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.stat", return_value=MagicMock(st_mtime=1000 - 3600))  # 1 hour old
        assert downloader._is_cache_valid(Path("/tmp/recent"))

    def test_is_cache_valid_when_file_is_old(self, mocker):
        downloader = SchemaDownloader()
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.stat", return_value=MagicMock(st_mtime=1000 - 100000))  # Older than TTL
        assert not downloader._is_cache_valid(Path("/tmp/old"))

    def test_get_schema_uses_cache_when_valid(self, mocker):
        downloader = SchemaDownloader()
        mocker.patch("traefik_validator.utils.SchemaDownloader._is_cache_valid", return_value=True)
        json_load_mock = mocker.patch("json.load", return_value={"test": "schema"})
        open_mock = mocker.patch("builtins.open", mocker.mock_open())
        
        schema = downloader.get_schema("https://example.com/schema.json")
        
        assert open_mock.called
        assert json_load_mock.called
        assert schema == {"test": "schema"}
        
    def test_get_schema_downloads_when_cache_invalid(self, mocker):
        downloader = SchemaDownloader()
        mocker.patch("traefik_validator.utils.SchemaDownloader._is_cache_valid", return_value=False)
        download_mock = mocker.patch(
            "traefik_validator.utils.SchemaDownloader.download_from_url", 
            return_value={"test": "downloaded"}
        )
        json_dump_mock = mocker.patch("json.dump")
        open_mock = mocker.patch("builtins.open", mocker.mock_open())
        
        schema = downloader.get_schema("https://example.com/schema.json")
        
        assert download_mock.called
        assert open_mock.called
        assert json_dump_mock.called
        assert schema == {"test": "downloaded"}
        
    def test_offline_mode_raises_error_when_no_cache(self, mocker):
        downloader = SchemaDownloader()
        mocker.patch("traefik_validator.utils.SchemaDownloader._is_cache_valid", return_value=False)
        mocker.patch("pathlib.Path.exists", return_value=False)
        
        with pytest.raises(ValueError) as excinfo:
            downloader.get_schema("https://example.com/schema.json", offline=True)
            
        assert "offline mode" in str(excinfo.value)
        
    def test_offline_mode_uses_expired_cache(self, mocker):
        downloader = SchemaDownloader()
        mocker.patch("traefik_validator.utils.SchemaDownloader._is_cache_valid", return_value=False)
        mocker.patch("pathlib.Path.exists", return_value=True)
        json_load_mock = mocker.patch("json.load", return_value={"test": "expired-cache"})
        open_mock = mocker.patch("builtins.open", mocker.mock_open())
        
        schema = downloader.get_schema("https://example.com/schema.json", offline=True)
        
        assert open_mock.called
        assert json_load_mock.called
        assert schema == {"test": "expired-cache"}