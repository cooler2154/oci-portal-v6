# backend/core/cache_config.py
"""
JDE Cache Management Configuration
Defines cache endpoints for each JDE environment (DV920, PY920, DM920)
"""
from typing import Dict, List, Any
from core.config import settings


# Per-cache config: each entry lists the individual cache endpoints to call
# All calls within one entry share a single auth token obtained at the start
CACHE_CONFIG: Dict[str, List[Dict[str, Any]]] = {
    "DV920": [
        {
            "path": "/clearjdbjdatabasecaches",
            "body": {
                "instanceName": "ndevrjas01_jas_dv920_01_1081",
                "jdbjDatabaseCacheName": "ALL"
            }
        },
        {
            "path": "/cleardatacaches",
            "body": {
                "instanceName": "ndevrjas01_ais_dv920_01_1181",
                "targetType": "restserver"
            }
        },
    ],
    "PY920": [
        {
            "path": "/clearjdbjdatabasecaches",
            "body": {
                "instanceName": "ndevrjas01_jas_PY920_01_1091",
                "jdbjDatabaseCacheName": "ALL"
            }
        },
        {
            "path": "/cleardatacaches",
            "body": {
                "instanceName": "ndevrjas01_ais_py920_01_1191",
                "targetType": "restserver"
            }
        },
    ],
    "DM920": [
        {
            "path": "/clearjdbjdatabasecaches",
            "body": {
                "instanceName": "ndevrjas01_jas_dm920_01_1083",
                "jdbjDatabaseCacheName": "ALL"
            }
        },
        {
            "path": "/cleardatacaches",
            "body": {
                "instanceName": "ndevrjas01_ais_dm920_01_1183",
                "targetType": "restserver"
            }
        },
    ],
}


def get_cache_api_base() -> str:
    """Get cache API base URL from settings"""
    return settings.CACHE_API_BASE.rstrip("/")


def get_cache_api_user() -> str:
    """Get cache API username from settings"""
    return settings.CACHE_API_USER


def get_cache_api_password() -> str:
    """Get cache API password from settings"""
    return settings.CACHE_API_PASSWORD


def get_cache_config(cache_name: str) -> List[Dict[str, Any]]:
    """
    Get cache configuration for a specific environment.
    
    Args:
        cache_name: Environment name (DV920, PY920, DM920)
    
    Returns:
        List of endpoint configurations
    
    Raises:
        ValueError: If cache_name is not recognized
    """
    cache_name = cache_name.upper()
    if cache_name not in CACHE_CONFIG:
        raise ValueError(f"Unknown cache '{cache_name}'. Valid options: {', '.join(CACHE_CONFIG.keys())}")
    return CACHE_CONFIG[cache_name]
