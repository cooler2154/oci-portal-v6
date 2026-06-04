# backend/routers/cache.py
"""
JDE Cache Management Router
Provides endpoints for clearing JDE database and data caches
"""
import requests as req
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.cache_config import (
    get_cache_api_base, 
    get_cache_api_user, 
    get_cache_api_password, 
    get_cache_config
)
from core.logging_setup import app_logger, audit_logger
from db.database import get_db
from db.models import AuditLog, User
from routers.auth import get_current_user, require_operator


router = APIRouter(prefix="/api/clearCaches", tags=["cache"])


class CacheAPIError(Exception):
    """Raised when cache API communication fails"""
    pass


async def get_cache_api_token() -> str:
    """
    Authenticate against the JDE cache management API and return a bearer token.
    Called once per clear-cache request; the token is then reused for
    all individual cache calls within that request.
    
    Returns:
        Bearer token for cache API authentication
    
    Raises:
        CacheAPIError: If authentication fails
    """
    try:
        cache_api_base = get_cache_api_base()
        cache_api_user = get_cache_api_user()
        cache_api_pass = get_cache_api_password()
        
        response = req.post(
            f"{cache_api_base}/authenticate",
            json={"username": cache_api_user, "password": cache_api_pass},
            timeout=10,
        )
        response.raise_for_status()
        
        # Token may be in headers or response body depending on API version
        token = response.headers.get("token") or response.json().get("token")
        
        if not token:
            raise CacheAPIError("No token received from cache API authentication")
        
        app_logger.debug(f"Cache API authentication successful")
        return token
        
    except req.exceptions.RequestException as e:
        error_msg = f"Cache API authentication failed: {str(e)}"
        app_logger.error(error_msg)
        raise CacheAPIError(error_msg)


async def call_cache_api(cache_name: str) -> List[Dict[str, Any]]:
    """
    Authenticate once, then call every endpoint listed for the given cache.
    Returns a list of results, one per endpoint called.
    
    Args:
        cache_name: Environment name (DV920, PY920, DM920)
    
    Returns:
        List of result dictionaries with path, status, and body
    
    Raises:
        CacheAPIError: If any cache operation fails
    """
    config = get_cache_config(cache_name)
    cache_api_base = get_cache_api_base()
    
    # Step 1 — authenticate and get token
    token = await get_cache_api_token()
    headers = {
        "token": token,
        "Content-Type": "application/json",
    }
    
    # Step 2 — call each endpoint in sequence using the same token
    results = []
    for endpoint in config:
        try:
            url = f"{cache_api_base}{endpoint['path']}"
            app_logger.debug(f"Calling cache endpoint: {url}")
            
            response = req.delete(
                url,
                json=endpoint["body"],
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
            result = {
                "path": endpoint["path"],
                "status": response.status_code,
                "body": response.text if response.text else "OK",
            }
            results.append(result)
            app_logger.info(f"Cache endpoint success: {endpoint['path']} ({response.status_code})")
            
        except req.exceptions.RequestException as e:
            error_msg = f"Cache endpoint failed: {endpoint['path']} - {str(e)}"
            app_logger.error(error_msg)
            raise CacheAPIError(error_msg)
    
    return results


@router.post("/{cache_name}")
async def clear_cache(
    cache_name: str,
    request: Request,
    current_user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Clear JDE caches for a specific environment (DV920, PY920, or DM920).
    
    Requires Operator or Admin role.
    
    Args:
        cache_name: Environment identifier (DV920, PY920, DM920)
        request: FastAPI request object
        current_user: Current authenticated user
        db: Database session
    
    Returns:
        JSON response with operation status and results
    
    Raises:
        HTTPException: If authentication fails or cache operation fails
    """
    cache_name = cache_name.upper()
    
    # Validate cache name
    try:
        get_cache_config(cache_name)
    except ValueError as e:
        app_logger.warning(f"Invalid cache requested: {cache_name} by {current_user.username}")
        raise HTTPException(status_code=400, detail=str(e))
    
    try:
        # Execute cache clearing
        results = await call_cache_api(cache_name)
        
        # Log the action to audit trail
        db.add(AuditLog(
            username=current_user.username,
            user_email=current_user.email,
            action=f"CACHE_CLEAR_{cache_name}",
            resource=f"JDE_{cache_name}",
            source_ip=request.client.host if request.client else "unknown",
            detail=f"{len(results)} cache endpoints cleared successfully"
        ))
        await db.commit()
        
        audit_logger.info(
            f"user={current_user.username} action=CACHE_CLEAR_{cache_name} "
            f"endpoints={len(results)} ip={request.client.host if request.client else 'unknown'}"
        )
        
        return {
            "ok": True,
            "message": f"Cache {cache_name}: {len(results)} caches cleared",
            "results": results,
        }
        
    except CacheAPIError as e:
        # Log the failure
        db.add(AuditLog(
            username=current_user.username,
            user_email=current_user.email,
            action=f"CACHE_CLEAR_{cache_name}_FAIL",
            resource=f"JDE_{cache_name}",
            source_ip=request.client.host if request.client else "unknown",
            detail=str(e)
        ))
        await db.commit()
        
        app_logger.error(f"Cache clear failed for {cache_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    except Exception as e:
        # Unexpected error
        app_logger.exception(f"Unexpected error clearing cache {cache_name}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
