"""
Configuration Loader Module.

This module provides utilities for loading YAML/JSON configuration files
and applying runtime overrides without modifying files on disk.
"""

import copy
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

logger = logging.getLogger(__name__)


def get_app_base_path() -> Path:
    """
    Get the base path for application resources.
    
    Handles both development mode and PyInstaller frozen executables.
    
    Returns:
        Path to the application base directory.
    """
    if getattr(sys, 'frozen', False):
        # Running in a PyInstaller bundle
        # The _MEIPASS attribute points to the temp folder for onefile,
        # or the bundle directory for onedir
        if hasattr(sys, '_MEIPASS'):
            return Path(sys._MEIPASS)
        else:
            return Path(sys.executable).parent
    else:
        # Running in normal Python environment
        return Path(__file__).parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    Get the absolute path to a resource file.
    
    Works both in development and when packaged with PyInstaller.
    
    Args:
        relative_path: Path relative to the Scripts directory.
        
    Returns:
        Absolute path to the resource.
    """
    base = get_app_base_path()
    return base / relative_path


def get_core_path(filename: str) -> Path:
    """
    Get the path to a file in the core directory.
    
    Args:
        filename: Name of the file in the core directory.
        
    Returns:
        Absolute path to the file.
    """
    return get_resource_path(f"core/{filename}")


class ConfigLoader:
    """
    Loads and manages configuration for API processing.
    
    Supports loading from YAML or JSON files, applying runtime overrides,
    and parsing dot-notation key paths for nested value updates.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the ConfigLoader.
        
        Args:
            config_path: Optional path to the configuration file.
        """
        self.config_path = config_path
        self._config: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        """
        Load configuration from the specified file.
        
        Returns:
            Dictionary containing the loaded configuration.
        
        Raises:
            FileNotFoundError: If config file does not exist.
            ValueError: If config file format is invalid.
        """
        if not self.config_path:
            logger.warning("No config path specified, returning empty config")
            return {}

        config_path = Path(self.config_path)
        
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                if config_path.suffix.lower() in ['.yaml', '.yml']:
                    self._config = yaml.safe_load(f) or {}
                    logger.info(f"✓ Loaded YAML config: {config_path.name}")
                else:
                    self._config = json.load(f)
                    logger.info(f"✓ Loaded JSON config: {config_path.name}")
                return copy.deepcopy(self._config)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")

    def get_config(self) -> Dict[str, Any]:
        """
        Get a deep copy of the current configuration.
        
        Returns:
            Deep copy of the configuration dictionary.
        """
        return copy.deepcopy(self._config)

    @staticmethod
    def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively merge override dictionary into base dictionary.
        
        For nested dictionaries, merges recursively. For lists and other types,
        override replaces base value completely.
        
        Args:
            base: Base dictionary to merge into.
            override: Dictionary with values to override.
        
        Returns:
            New dictionary with merged values.
        """
        result = copy.deepcopy(base)
        
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = ConfigLoader.deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        
        return result

    @staticmethod
    def apply_dot_notation_overrides(
        config: Dict[str, Any],
        overrides: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply overrides using dot notation for nested keys.
        
        Supports keys like:
        - "prompt" -> config["prompt"]
        - "tasks.0.prompt" -> config["tasks"][0]["prompt"]
        - "model_version" -> config["model_version"]
        
        Args:
            config: Base configuration dictionary.
            overrides: Dictionary with dot-notation keys and values.
        
        Returns:
            New dictionary with overrides applied.
        """
        result = copy.deepcopy(config)
        
        for key_path, value in overrides.items():
            ConfigLoader._set_nested_value(result, key_path, value)
        
        return result

    @staticmethod
    def _set_nested_value(
        config: Dict[str, Any],
        key_path: str,
        value: Any
    ) -> None:
        """
        Set a nested value in the config using dot notation.
        
        Args:
            config: Configuration dictionary to modify in place.
            key_path: Dot-separated path to the key (e.g., "tasks.0.prompt").
            value: Value to set at the specified path.
        """
        keys = key_path.split('.')
        current = config
        
        for i, key in enumerate(keys[:-1]):
            if key.isdigit():
                key = int(key)
                if isinstance(current, list) and key < len(current):
                    current = current[key]
                else:
                    logger.warning(f"Invalid index {key} in path '{key_path}'")
                    return
            else:
                if key not in current:
                    current[key] = {}
                current = current[key]
        
        final_key = keys[-1]
        if final_key.isdigit():
            final_key = int(final_key)
            if isinstance(current, list) and final_key < len(current):
                current[final_key] = value
            else:
                logger.warning(f"Cannot set index {final_key} in path '{key_path}'")
        else:
            current[final_key] = value

    @staticmethod
    def parse_override_text(text: str) -> Dict[str, Any]:
        """
        Parse override text from the GUI advanced section.
        
        Supports formats:
        - key = value
        - key=value
        - key: value
        
        Automatically converts string values to appropriate types
        (int, float, bool, or str).
        
        Args:
            text: Multi-line text containing key-value pairs.
        
        Returns:
            Dictionary with parsed key-value pairs.
        """
        overrides = {}
        
        if not text or not text.strip():
            return overrides
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            match = re.match(r'^([a-zA-Z0-9_.]+)\s*[:=]\s*(.+)$', line)
            if match:
                key = match.group(1).strip()
                value_str = match.group(2).strip()
                
                value_str = value_str.strip('"\'')
                
                value = ConfigLoader._parse_value(value_str)
                overrides[key] = value
            else:
                logger.warning(f"Could not parse override line: {line}")
        
        return overrides

    @staticmethod
    def _parse_value(value_str: str) -> Any:
        """
        Parse a string value to the appropriate Python type.
        
        Args:
            value_str: String representation of the value.
        
        Returns:
            Parsed value as int, float, bool, or str.
        """
        if value_str.lower() == 'true':
            return True
        if value_str.lower() == 'false':
            return False
        if value_str.lower() == 'none' or value_str.lower() == 'null':
            return None
        
        try:
            return int(value_str)
        except ValueError:
            pass
        
        try:
            return float(value_str)
        except ValueError:
            pass
        
        return value_str


def _resolve_task_paths(config: Dict[str, Any], base_dir: Path) -> Dict[str, Any]:
    """
    Resolve relative paths in config and task configurations to absolute paths.

    Handles both top-level config keys (base_folder, output_folder, root_folder)
    and per-task path keys so that all relative paths are resolved from the
    current working directory.

    Args:
        config: Configuration dictionary with tasks.
        base_dir: Base directory for resolving relative paths (current working dir).

    Returns:
        Configuration with resolved absolute paths.
    """
    path_keys = ['folder', 'reference_folder', 'output_folder', 'base_folder']
    top_level_path_keys = ['base_folder', 'output_folder', 'root_folder']
    resolved_count = 0
    missing_paths = []

    # Resolve top-level relative paths
    for key in top_level_path_keys:
        if key in config and config[key]:
            original_path = config[key]
            path_obj = Path(original_path)
            if not path_obj.is_absolute():
                resolved_path = (base_dir / original_path).resolve()
                config[key] = str(resolved_path)
                resolved_count += 1

    # Resolve per-task relative paths
    tasks = config.get('tasks', [])
    for i, task in enumerate(tasks):
        for key in path_keys:
            if key in task and task[key]:
                original_path = task[key]
                path_obj = Path(original_path)

                # Only resolve if it's a relative path
                if not path_obj.is_absolute():
                    resolved_path = (base_dir / original_path).resolve()
                    task[key] = str(resolved_path)
                    resolved_count += 1

                    # Check if the resolved path exists
                    if not resolved_path.exists():
                        missing_paths.append((i + 1, key, str(resolved_path)))

    if resolved_count > 0:
        logger.debug(f"Resolved {resolved_count} relative paths in configurations")

    if missing_paths:
        logger.warning(f"⚠️ {len(missing_paths)} resolved path(s) do not exist:")
        for task_num, key, path in missing_paths[:3]:  # Show first 3
            logger.warning(f"   Task {task_num} {key}: {path}")
        if len(missing_paths) > 3:
            logger.warning(f"   ... and {len(missing_paths) - 3} more")
        logger.warning(f"   Hint: Check that 'Working Directory' is set to the correct project folder")

    return config


def load_and_merge_config(
    config_path: Optional[str] = None,
    runtime_overrides: Optional[Dict[str, Any]] = None,
    resolve_paths: bool = True
) -> Dict[str, Any]:
    """
    Load configuration and apply runtime overrides.
    
    This is the main entry point for loading configs with GUI overrides.
    Overrides are applied without modifying the file on disk.
    
    Args:
        config_path: Path to the YAML or JSON configuration file.
        runtime_overrides: Dictionary of overrides to apply. Can use
            dot notation for nested keys (e.g., "tasks.0.prompt").
        resolve_paths: If True, resolve relative paths in tasks to absolute
            paths based on the current working directory.
    
    Returns:
        Merged configuration dictionary.
    
    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If config file format is invalid.
    """
    loader = ConfigLoader(config_path)
    config = loader.load()
    
    if runtime_overrides:
        dot_notation_overrides = {}
        dict_overrides = {}
        
        for key, value in runtime_overrides.items():
            if '.' in key:
                dot_notation_overrides[key] = value
            elif isinstance(value, dict):
                dict_overrides[key] = value
            else:
                dot_notation_overrides[key] = value
        
        if dict_overrides:
            config = ConfigLoader.deep_merge(config, dict_overrides)
        
        if dot_notation_overrides:
            config = ConfigLoader.apply_dot_notation_overrides(
                config, dot_notation_overrides
            )
    
    # Resolve relative paths in tasks based on current working directory
    if resolve_paths:
        import os
        config = _resolve_task_paths(config, Path(os.getcwd()))
    
    return config


def get_default_config_path(api_name: str) -> Optional[str]:
    """
    Get the default config file path for an API.
    
    Args:
        api_name: Internal API name (e.g., "kling", "nano_banana").
    
    Returns:
        Path to the default config file, or None if not found.
    """
    script_dir = Path(__file__).parent.parent
    config_dir = script_dir / "config"
    
    yaml_path = config_dir / f"batch_{api_name}_config.yaml"
    if yaml_path.exists():
        return str(yaml_path)
    
    json_path = config_dir / f"batch_{api_name}_config.json"
    if json_path.exists():
        return str(json_path)
    
    return None


def get_env_file_path() -> Path:
    """
    Get the path to the .env file.

    For PyInstaller builds, the .env file lives next to the executable
    (not inside the temp _MEIPASS bundle). For development, it lives in
    the Scripts directory.

    Returns:
        Absolute path to the .env file location.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / ".env"
    return Path(__file__).parent.parent / ".env"


def load_env_file() -> None:
    """
    Load environment variables from a .env file.

    Reads key=value pairs and sets them as environment variables.
    Does not overwrite variables that are already set in the environment.
    Lines starting with '#' and blank lines are ignored.
    """
    env_path = get_env_file_path()
    if not env_path.exists():
        return

    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                # Do not overwrite existing environment variables
                if key not in os.environ:
                    os.environ[key] = value
    except OSError:
        logger.warning(f"Could not read .env file: {env_path}")


def save_testbed_cookie(cookie: str) -> Path:
    """
    Save the testbed cookie to the .env file.

    Creates the file if it doesn't exist. If it already exists, updates
    or appends the TESTBED_COOKIE line while preserving other content.
    Also removes any bare cookie lines (raw cookie value without the
    TESTBED_COOKIE= prefix) that may have been written by earlier code.

    Args:
        cookie: The cookie string to save.

    Returns:
        The path to the .env file that was written.
    """
    env_path = get_env_file_path()
    lines: list[str] = []
    found = False

    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('TESTBED_COOKIE=') or stripped == 'TESTBED_COOKIE=':
                    lines.append(f"TESTBED_COOKIE={cookie}\n")
                    found = True
                elif stripped == cookie:
                    # Remove bare cookie value lines (no TESTBED_COOKIE= prefix)
                    pass
                else:
                    lines.append(line)

    if not found:
        lines.append(f"TESTBED_COOKIE={cookie}\n")

    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    # Also update the in-memory environment variable
    os.environ['TESTBED_COOKIE'] = cookie
    return env_path


SUPPORTED_BROWSERS = ['brave', 'chrome', 'edge', 'safari', 'firefox', 'chromium', 'arc', 'opera', 'vivaldi']


def load_browser_preference() -> str:
    """
    Load the preferred browser name from the .env file.
    Change the browser preference by setting TESTBED_BROWSER in the .env file or by changing the browser name in the following code to one of the supported browsers.

    Returns:
        Browser name string, or 'brave' if not set.
    """
    load_env_file()
    return os.environ.get('TESTBED_BROWSER', 'brave')


def save_browser_preference(browser: str) -> None:
    """
    Save the preferred browser name to the .env file.

    Args:
        browser: Browser name to save (e.g. 'brave', 'chrome').
    """
    env_path = get_env_file_path()
    lines: list[str] = []
    found = False

    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('TESTBED_BROWSER='):
                    lines.append(f"TESTBED_BROWSER={browser}\n")
                    found = True
                else:
                    lines.append(line)

    if not found:
        lines.append(f"TESTBED_BROWSER={browser}\n")

    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    os.environ['TESTBED_BROWSER'] = browser


def fetch_cookie_from_browser(
    domain: str = '192.168.31.18',
    browser: str = 'brave',
) -> str:
    """
    Fetch cookies for a given domain directly from the specified browser profile.

    Uses browser-cookie3 to read and decrypt the browser's on-disk cookie store.
    The browser must have visited the domain at least once and the session must
    still be valid. On macOS, the system may prompt once for Keychain access.

    Args:
        domain: Hostname (or IP) to match against stored cookies.
        browser: Browser name supported by browser-cookie3 (e.g. 'brave',
            'chrome', 'edge', 'safari', 'firefox'). Defaults to 'brave'.

    Returns:
        Cookie header string (e.g. "name1=val1; name2=val2"), or empty string
        if browser-cookie3 is not installed or no matching cookies are found.
    """
    try:
        import browser_cookie3
    except ImportError:
        logger.debug("browser-cookie3 not installed; skipping browser cookie fetch")
        return ''

    try:
        loader = getattr(browser_cookie3, browser, None)
        if loader is None:
            logger.warning(f"browser-cookie3 does not support browser: {browser}")
            return ''
        jar = loader(domain_name=domain)
        pairs = [f"{c.name}={c.value}" for c in jar]
        if not pairs:
            logger.debug(f"No cookies found for domain '{domain}' in {browser}")
            return ''
        return '; '.join(pairs)
    except Exception as e:
        logger.debug(f"Could not fetch cookies from {browser}: {e}")
        return ''


def get_testbed_cookie(auto_fetch: bool = True, browser: Optional[str] = None) -> str:
    """
    Get the testbed cookie from the environment.

    Resolution order:
    1. Specified browser's cookie store (freshest session, triggers Keychain once).
    2. TESTBED_COOKIE environment variable / .env file (fallback if browser
       returns nothing or auto_fetch=False).

    When the cookie is obtained from the browser it is also persisted to
    the .env file so it can serve as a fallback when the browser is unavailable.

    Args:
        auto_fetch: If True, try reading cookies from the browser first before
            falling back to the environment or .env file.
        browser: Browser to read cookies from (e.g. 'brave', 'chrome', 'edge',
            'safari', 'firefox'). If None, reads from TESTBED_BROWSER in .env
            or defaults to 'brave'.

    Returns:
        The cookie string, or empty string if not found anywhere.
    """
    if auto_fetch:
        chosen_browser = browser or load_browser_preference()
        # Read the existing .env cookie once for staleness comparison
        load_env_file()
        existing_cookie = os.environ.get('TESTBED_COOKIE', '')
        # Try each known testbed host until we find cookies
        testbed_hosts = ['192.168.31.161', '210.244.31.18']
        for host in testbed_hosts:
            cookie = fetch_cookie_from_browser(domain=host, browser=chosen_browser)
            if cookie:
                if cookie == existing_cookie:
                    logger.warning(
                        f"Auto-fetched cookie from {chosen_browser} (domain: {host}) matches the "
                        f"existing .env cookie — the browser may not have flushed a new session to "
                        f"disk yet. If you just logged in, try closing {chosen_browser} completely "
                        f"and re-running, or manually paste the new cookie into .env."
                    )
                else:
                    logger.info(f"Auto-fetched testbed cookie from {chosen_browser} (domain: {host})")
                    try:
                        save_testbed_cookie(cookie)
                        logger.info("Auto-fetched cookie saved to .env")
                    except OSError as e:
                        logger.warning(f"Could not persist auto-fetched cookie: {e}")
                return cookie

    # Fall back to .env file / environment variable
    load_env_file()
    return os.environ.get('TESTBED_COOKIE', '')
