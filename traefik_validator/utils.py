import json
import os
import sys
import time
import jsonschema
import yaml
import urllib.request
from io import TextIOWrapper
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any, NoReturn


from traefik_validator import settings


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


class SchemaDownloader:
    """
    A class for downloading and caching Traefik JSON schemas.
    
    The schemas are cached locally to avoid repeated downloads and
    to support offline validation. The cache has a configurable TTL.
    """
    CACHE_DIR = Path.home() / ".traefik-validator" / "cache"
    CACHE_TTL = 86400  # 24 hours in seconds
    
    def __init__(self):
        self.static_schema_url = settings.STATIC_CONFS_SCHEMA_URL
        self.dynamic_schema_url = settings.DYNAMIC_CONFS_SCHEMA_URL
        os.makedirs(self.CACHE_DIR, exist_ok=True)
    
    def _get_cache_path(self, url: str) -> Path:
        """Generate a cache file path for a given URL"""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return self.CACHE_DIR / f"{url_hash}.json"
    
    def _is_cache_valid(self, cache_path: Path) -> bool:
        """Check if cache file exists and is not older than TTL"""
        if not cache_path.exists():
            return False
        
        cache_age = time.time() - cache_path.stat().st_mtime
        return cache_age < self.CACHE_TTL
    
    def download_from_url(self, url: str) -> Dict[str, Any]:
        """Download schema file from given URL"""
        try:
            with urllib.request.urlopen(url) as f:
                schema = json.loads(f.read().decode('utf-8'))
            return schema
        except urllib.error.URLError as e:
            raise ValueError(f"Failed to download schema from {url}: {e}")
    
    def get_schema(self, url: str, offline: bool = False) -> Dict[str, Any]:
        """Get schema from cache or download if needed"""
        cache_path = self._get_cache_path(url)
        
        # Check cache first
        if self._is_cache_valid(cache_path):
            with open(cache_path, 'r') as f:
                return json.load(f)
                
        # If offline mode and no valid cache, raise error
        if offline:
            if cache_path.exists():
                # Use expired cache in offline mode
                with open(cache_path, 'r') as f:
                    return json.load(f)
            else:
                raise ValueError(
                    f"No cached schema available for {url} and offline mode is enabled. "
                    f"Run without --offline first to download schemas."
                )
        
        # Download fresh schema
        schema = self.download_from_url(url)
        
        # Save to cache
        with open(cache_path, 'w') as f:
            json.dump(schema, f)
        
        return schema
    
    def get_static_schema(self, offline: bool = False) -> Dict[str, Any]:
        """Get the static configuration schema"""
        return self.get_schema(self.static_schema_url, offline)
    
    def get_dynamic_schema(self, offline: bool = False) -> Dict[str, Any]:
        """Get the dynamic configuration schema"""
        return self.get_schema(self.dynamic_schema_url, offline)


class Validator:
    """
    Validates user YAML files against Traefik JSON schemas.
    
    User should provide at least one of:
    - static_conf_file: for validating Traefik static configuration
    - dynamic_conf_file: for validating Traefik dynamic configuration
    
    The validator can work in online mode (default) or offline mode.
    In offline mode, it will use cached schemas without attempting to download.
    """
    def __init__(
            self,
            static_conf_file: Optional[TextIOWrapper] = None,
            dynamic_conf_file: Optional[TextIOWrapper] = None,
            offline: bool = False
    ):
        if not any([static_conf_file, dynamic_conf_file]):
            raise ValueError("User should pass either static config file or dynamic config file")

        self.static_conf_file = static_conf_file
        self.dynamic_conf_file = dynamic_conf_file
        self.offline = offline
        self.schema_downloader = SchemaDownloader()

    def validate(self) -> None:
        """
        Validate provided configuration files.
        
        This method attempts to validate both static and dynamic configuration files
        if they were provided. It collects and reports all validation errors.
        
        Raises:
            ValidationError: If any configuration file fails validation
        """
        validation_errors = []
        
        # Validate static configuration if provided
        if self.static_conf_file:
            try:
                self._validate_static()
                print("\033[92m✓\033[0m Static configuration is valid")
            except jsonschema.exceptions.ValidationError as e:
                validation_errors.append(("static", e))
                path = " → ".join(str(p) for p in e.path) if e.path else "root"
                print(f"\033[91m✗\033[0m Static configuration error: {e.message}")
                print(f"   at: {path}")
        
        # Validate dynamic configuration if provided
        if self.dynamic_conf_file:
            try:
                self._validate_dynamic()
                print("\033[92m✓\033[0m Dynamic configuration is valid")
            except jsonschema.exceptions.ValidationError as e:
                validation_errors.append(("dynamic", e))
                path = " → ".join(str(p) for p in e.path) if e.path else "root"
                print(f"\033[91m✗\033[0m Dynamic configuration error: {e.message}")
                print(f"   at: {path}")
        
        # If any validation errors, raise a ValidationError
        if validation_errors:
            raise ValidationError("Configuration validation failed")

    def _validate_static(self) -> None:
        """
        Validate static configuration file.
        
        Raises:
            jsonschema.exceptions.ValidationError: If validation fails
        """
        if not self.static_conf_file:
            return

        schema_file = self.schema_downloader.get_static_schema(offline=self.offline)
        config_file = self.load_yaml(self.static_conf_file)
        jsonschema.validate(instance=config_file, schema=schema_file)

    def _validate_dynamic(self) -> None:
        """
        Validate dynamic configuration file.
        
        Raises:
            jsonschema.exceptions.ValidationError: If validation fails
        """
        if not self.dynamic_conf_file:
            return

        schema_file = self.schema_downloader.get_dynamic_schema(offline=self.offline)
        config_file = self.load_yaml(self.dynamic_conf_file)
        jsonschema.validate(instance=config_file, schema=schema_file)

    @staticmethod
    def load_yaml(file: TextIOWrapper) -> Dict[str, Any]:
        """
        Load and parse YAML file safely.
        
        Args:
            file: A file-like object containing YAML content
            
        Returns:
            Parsed YAML content as a dictionary
        """
        return yaml.safe_load(file)