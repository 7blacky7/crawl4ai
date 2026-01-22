# ───────────────────────── settings_routes.py ─────────────────────────
"""
Settings API for Crawl4AI Web UI
- GET /settings - Returns current settings + schema
- POST /settings - Saves settings to ~/.crawl4ai/global.yml
- GET /settings/claude-oauth-status - Checks Claude CLI OAuth status
"""

import os
import yaml
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Import USER_SETTINGS from config
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
try:
    from crawl4ai.config import USER_SETTINGS
except ImportError:
    # Fallback if import fails
    USER_SETTINGS = {
        "DEFAULT_LLM_PROVIDER": {
            "default": "openai/gpt-4o",
            "description": "Default LLM provider in 'company/model' format",
            "type": "string"
        },
        "DEFAULT_LLM_PROVIDER_TOKEN": {
            "default": "",
            "description": "API token for the default LLM provider",
            "type": "string",
            "secret": True
        },
        "VERBOSE": {
            "default": False,
            "description": "Enable verbose output for all commands",
            "type": "boolean"
        },
        "BROWSER_HEADLESS": {
            "default": True,
            "description": "Run browser in headless mode by default",
            "type": "boolean"
        },
        "BROWSER_TYPE": {
            "default": "chromium",
            "description": "Default browser type (chromium or firefox)",
            "type": "string",
            "options": ["chromium", "firefox"]
        },
        "CACHE_MODE": {
            "default": "bypass",
            "description": "Default cache mode (bypass, use, or refresh)",
            "type": "string",
            "options": ["bypass", "use", "refresh"]
        },
        "USER_AGENT_MODE": {
            "default": "default",
            "description": "Default user agent mode (default, random, or mobile)",
            "type": "string",
            "options": ["default", "random", "mobile"]
        }
    }

router = APIRouter(prefix="/settings", tags=["settings"])


# ────────────────────────── Helpers ──────────────────────────

def get_config_path() -> Path:
    """Get the path to the global config file."""
    return Path.home() / ".crawl4ai" / "global.yml"


def load_global_config() -> Dict[str, Any]:
    """Load the global configuration from ~/.crawl4ai/global.yml"""
    config_path = get_config_path()

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def save_global_config(config: Dict[str, Any]) -> bool:
    """Save configuration to ~/.crawl4ai/global.yml"""
    config_path = get_config_path()

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False)
        return True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {str(e)}")


def mask_secret(value: str) -> str:
    """Mask a secret value for display."""
    if not value:
        return ""
    if len(value) <= 8:
        return "********"
    return value[:4] + "****" + value[-4:]


def check_claude_cli_installed() -> bool:
    """Check if Claude CLI is installed."""
    return shutil.which("claude") is not None


def check_claude_oauth_status() -> Dict[str, Any]:
    """Check Claude CLI OAuth status."""
    result = {
        "cli_installed": False,
        "logged_in": False,
        "user": None,
        "error": None
    }

    # Check if CLI is installed
    if not check_claude_cli_installed():
        result["error"] = "Claude CLI not installed"
        return result

    result["cli_installed"] = True

    # Try to get auth status
    try:
        proc = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10
        )

        output = proc.stdout + proc.stderr

        # Parse output to determine login status
        if "logged in" in output.lower() or "authenticated" in output.lower():
            result["logged_in"] = True
            # Try to extract user info
            for line in output.split("\n"):
                if "@" in line:
                    result["user"] = line.strip()
                    break
        elif proc.returncode != 0:
            result["error"] = "Not logged in"

    except subprocess.TimeoutExpired:
        result["error"] = "Timeout checking auth status"
    except Exception as e:
        result["error"] = str(e)

    return result


# ────────────────────────── Schemas ──────────────────────────

class SettingsUpdate(BaseModel):
    settings: Dict[str, Any]


class SettingsResponse(BaseModel):
    settings: Dict[str, Any]
    schema_: Dict[str, Any]
    config_path: str


class ClaudeOAuthStatus(BaseModel):
    cli_installed: bool
    logged_in: bool
    user: Optional[str] = None
    error: Optional[str] = None


# ────────────────────────── Endpoints ──────────────────────────

@router.get("")
async def get_settings() -> Dict[str, Any]:
    """
    Get current settings with their schema.
    Secret values are masked for display.
    """
    config = load_global_config()

    # Build response with current values and schema
    settings = {}
    schema = {}

    for key, setting_def in USER_SETTINGS.items():
        # Get current value or default
        value = config.get(key, setting_def["default"])

        # Mask secret values
        if setting_def.get("secret", False) and value:
            display_value = mask_secret(str(value))
        else:
            display_value = value

        settings[key] = {
            "value": display_value,
            "raw_value_set": key in config  # Indicates if user has set this value
        }

        schema[key] = {
            "type": setting_def["type"],
            "default": setting_def["default"],
            "description": setting_def["description"],
            "secret": setting_def.get("secret", False),
            "options": setting_def.get("options")
        }

    return {
        "settings": settings,
        "schema": schema,
        "config_path": str(get_config_path())
    }


@router.post("")
async def update_settings(data: SettingsUpdate) -> Dict[str, Any]:
    """
    Update settings in ~/.crawl4ai/global.yml
    """
    config = load_global_config()
    updated_keys = []
    errors = []

    for key, value in data.settings.items():
        # Validate key exists in schema
        if key not in USER_SETTINGS:
            errors.append(f"Unknown setting: {key}")
            continue

        setting_def = USER_SETTINGS[key]

        # Type conversion and validation
        try:
            if setting_def["type"] == "boolean":
                if isinstance(value, bool):
                    typed_value = value
                elif isinstance(value, str):
                    if value.lower() in ["true", "yes", "1", "y"]:
                        typed_value = True
                    elif value.lower() in ["false", "no", "0", "n"]:
                        typed_value = False
                    else:
                        errors.append(f"{key}: Invalid boolean value")
                        continue
                else:
                    typed_value = bool(value)

            elif setting_def["type"] == "string":
                typed_value = str(value)

                # Validate against options if defined
                if "options" in setting_def and typed_value not in setting_def["options"]:
                    errors.append(f"{key}: Must be one of {setting_def['options']}")
                    continue
            else:
                typed_value = value

            # Don't update if value is masked (secret field unchanged)
            if setting_def.get("secret", False) and "****" in str(value):
                continue

            config[key] = typed_value
            updated_keys.append(key)

        except Exception as e:
            errors.append(f"{key}: {str(e)}")

    # Save if any valid updates
    if updated_keys:
        save_global_config(config)

    return {
        "success": len(errors) == 0,
        "updated": updated_keys,
        "errors": errors,
        "config_path": str(get_config_path())
    }


@router.get("/claude-oauth-status")
async def get_claude_oauth_status() -> ClaudeOAuthStatus:
    """
    Check Claude CLI OAuth status.
    Returns whether CLI is installed and if user is logged in.
    """
    status = check_claude_oauth_status()
    return ClaudeOAuthStatus(**status)


@router.post("/reset")
async def reset_settings() -> Dict[str, Any]:
    """
    Reset all settings to their default values.
    """
    config_path = get_config_path()

    try:
        if config_path.exists():
            config_path.unlink()
        return {
            "success": True,
            "message": "Settings reset to defaults",
            "config_path": str(config_path)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset settings: {str(e)}")
