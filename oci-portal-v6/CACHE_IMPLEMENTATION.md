# JDE Cache Management Implementation

## Overview

This document describes the complete JDE cache clearing functionality integrated into the OCI Portal v2.0.

## Components

### 1. Backend Configuration (`backend/core/cache_config.py`)

Defines cache endpoints for three JDE environments:

- **DV920** (Development)
- **PY920** (Pre-Production)  
- **DM920** (Demo)

Each environment has two cache endpoints:
1. `/clearjdbjdatabasecaches` - Clears JDBJ database caches
2. `/cleardatacaches` - Clears AIS data caches

**Configuration via environment variables:**
```bash
CACHE_API_BASE=http://JDESMC/manage/mgmtrestservice
CACHE_API_USER=jde_admin
CACHE_API_PASSWORD=jde_admin
```

### 2. Backend API Router (`backend/routers/cache.py`)

Provides the following endpoint:

```
POST /api/clearCaches/{cache_name}
```

**Requirements:**
- Operator or Admin role
- Valid JWT authentication token
- `cache_name` must be one of: DV920, PY920, DM920

**Response on success:**
```json
{
  "ok": true,
  "message": "Cache DV920: 2 caches cleared",
  "results": [
    {
      "path": "/clearjdbjdatabasecaches",
      "status": 200,
      "body": "OK"
    },
    {
      "path": "/cleardatacaches",
      "status": 200,
      "body": "OK"
    }
  ]
}
```

**Response on error:**
```json
{
  "detail": "Cache API authentication failed: [error details]"
}
```

**Audit Logging:**
All cache clearing operations are logged to the audit trail with:
- `action`: CACHE_CLEAR_{CACHE_NAME} or CACHE_CLEAR_{CACHE_NAME}_FAIL
- `resource`: JDE_{CACHE_NAME}
- `detail`: Success message or error details
- `source_ip`: User's IP address

### 3. Frontend UI (`backend/templates/partials/tab_cache.html`)

**Features:**
- Responsive grid layout with three cache environment cards
- Color-coded environment indicators (blue for DV, amber for PY, green for DM)
- Clear visual hierarchy and user guidance
- Real-time status feedback with icons and colors
- Warning message about cache clearing impact
- Information section explaining cache operations

**Elements:**
- Three cache cards (DV920, PY920, DM920)
- Clear cache button on each card
- Result display area showing operation status
- Information box with operation details
- Warning banner about impact

### 4. Frontend JavaScript (`static/js/cache-functions.js`)

**Main functions:**

#### `clearCache(cacheName)`
Calls the backend API to clear cache for the specified environment.

**Behavior:**
1. Validates token availability
2. Disables button and shows loading state
3. Sends POST request to `/api/clearCaches/{cacheName}`
4. Displays success/error results
5. Shows toast notification
6. Re-enables button

**Error handling:**
- Token not found
- Network errors
- API authentication failures
- Cache operation failures

#### `openCacheConfig()`
Placeholder for future cache configuration UI (admin only).

#### `initCacheTab()`
Initializes cache tab with hover effects and event listeners.

### 5. Main App Registration (`backend/main.py`)

Cache router is imported and registered:
```python
from routers import auth, users, instances, audit, debug, cache
...
app.include_router(cache.router)
```

## Installation & Configuration

### 1. Copy environment template
```bash
cp backend/.env.example backend/.env
```

### 2. Update cache API credentials in `.env`
```env
CACHE_API_BASE=http://JDESMC/manage/mgmtrestservice
CACHE_API_USER=jde_admin
CACHE_API_PASSWORD=jde_admin
```

### 3. Update cache instance names

Edit `backend/core/cache_config.py` and update instance names:
```python
"DV920": [
    {
        "path": "/clearjdbjdatabasecaches",
        "body": {
            "instanceName": "YOUR_INSTANCE_NAME",
            "jdbjDatabaseCacheName": "ALL"
        }
    },
    ...
]
```

### 4. Install dependencies

Ensure `requests` library is in `requirements.txt`:
```
requests>=2.28.0
```

### 5. Start the application
```bash
cd backend
uvicorn main:app --reload
```

## Usage

1. Log in to the OCI Portal with an Operator or Admin account
2. Click the "Clear Cache" tab in the tab bar
3. Select the environment you want to clear (DV920, PY920, or DM920)
4. Click the "Clear Cache" button on the card
5. Wait for the operation to complete
6. View the results showing which caches were cleared

## API Flow

```
User clicks "Clear Cache" button (Frontend)
    ↓
clearCache(cacheName) executes (JavaScript)
    ↓
POST /api/clearCaches/{cache_name} (API)
    ↓
Authentication check (JWT token validation)
    ↓
get_cache_config(cache_name) - Validate environment name
    ↓
get_cache_api_token() - Authenticate with JDE Cache API
    ↓
call_cache_api(cache_name) - Call each endpoint
    ↓
Log to audit trail
    ↓
Return results to frontend
    ↓
Display status with toast notification
```

## Security Considerations

1. **Role-Based Access:** Only Operators and Admins can clear caches
2. **Audit Logging:** All cache operations are logged with username, timestamp, and IP
3. **Token-Based Auth:** Uses JWT bearer tokens, not stored in frontend
4. **API Credentials:** Stored in environment variables, not in code
5. **CORS Protection:** Restricted to configured origins
6. **Error Handling:** Sensitive details are not exposed to frontend

## Troubleshooting

### "Authentication token not found"
- User is not logged in
- Browser session expired
- **Solution:** Log in again

### "Cache API authentication failed"
- CACHE_API_BASE URL is incorrect
- CACHE_API_USER or CACHE_API_PASSWORD is wrong
- JDE Cache API is unreachable
- **Solution:** Check `.env` configuration and network connectivity

### "Unknown cache 'XXX'"
- Cache name is misspelled or invalid
- **Solution:** Use one of: DV920, PY920, DM920

### "Only admins can configure cache settings"
- User tried to access cache configuration (future feature)
- **Solution:** Log in with an admin account or contact administrator

## Future Enhancements

1. **Cache Configuration UI** - Allow admins to configure cache endpoints via UI
2. **Scheduled Cache Clearing** - Automatic cache clearing on a schedule
3. **Bulk Operations** - Clear multiple caches at once
4. **Cache Status Monitoring** - Display cache health and usage statistics
5. **Notification System** - Send alerts when cache operations complete

## Testing

### Manual Testing

```bash
# Test cache clearing with curl
curl -X POST http://localhost:8000/api/clearCaches/DV920 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json"
```

### Expected Response

```json
{
  "ok": true,
  "message": "Cache DV920: 2 caches cleared",
  "results": [
    {
      "path": "/clearjdbjdatabasecaches",
      "status": 200,
      "body": "OK"
    },
    {
      "path": "/cleardatacaches",
      "status": 200,
      "body": "OK"
    }
  ]
}
```

## Support

For issues or questions:
1. Check the audit log in the portal (Audit log tab)
2. Review application logs in `debug.log`
3. Check audit logs in `audit.log`
4. Verify environment configuration in `.env`
