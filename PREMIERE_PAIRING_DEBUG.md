# Premiere Bridge Pairing - Troubleshooting Guide

## Issue: "Pairing code is invalid, expired, or already used"

This error occurs when the Premiere extension cannot successfully pair with the AI Render backend. Here are the fixes and troubleshooting steps.

## What was fixed

### 1. Backend Port Detection (Most Common Issue)
**Problem**: The Premiere extension hardcoded port 8000, but didn't know if that's where the backend was running.

**Fix**: The web frontend now stores the correct backend port in `localStorage` when you click "Connect inside Premiere". The Premiere extension reads this and connects to the correct port.

### 2. Better Error Messages
**Problem**: Error messages were generic and didn't help diagnose the real issue.

**Fix**: 
- The Premiere extension now validates the code format before sending it
- If the connection fails, it tells you exactly which port it's trying to reach
- The backend now returns more specific error messages

### 3. Code Format Validation
**Problem**: The placeholder showed the wrong format (AB-CD-EF instead of the actual format).

**Fix**: Updated to show correct format: `ABCD-EFGH-IJKL` (12 hex digits in 4-4-4 groups)

## Troubleshooting Steps

### Step 1: Verify Backend is Running
```bash
# Check if the backend is accessible
curl http://localhost:8000/

# Expected response: {"ok":true,"service":"rafiei-ai-editor","stage":3}
```

### Step 2: Check the Pairing Code Format
The code should be in this format: `ABCD-EFGH-IJKL`
- 12 hexadecimal characters (0-9, A-F)
- Separated by hyphens: 4-4-4 groups
- **Case insensitive** (the extension will uppercase it)

### Step 3: Verify localStorage is Set
Open the browser's Developer Tools (F12) and run:
```javascript
localStorage.getItem("airender_port")
```

This should return `"8000"` if running locally.

### Step 4: Check Active Sessions (Debug Endpoint)
If you're running the backend locally, visit:
```
http://localhost:8000/integrations/premiere/bridge/debug
```

This shows:
- How many sessions are active
- Whether your pairing code's session exists
- How long the code is valid for
- The current state of each session

### Step 5: Timing Issues
The pairing code **expires after 15 minutes**. Make sure you:
1. ✅ Click "Connect inside Premiere" button
2. ✅ Note the pairing code
3. ✅ Open Premiere extension **within 15 minutes**
4. ✅ Enter the code **before it expires**

The code can only be used **once** - after you use it, it's consumed.

## Common Scenarios

### Scenario A: "Cannot reach AI Render on http://127.0.0.1:8000"
**Cause**: Backend isn't running on port 8000

**Solution**:
1. Check if backend is running: `ps aux | grep uvicorn`
2. Start backend: `cd /Users/amirhossein/Documents/AI_render && python -m app.main --port 8000`
3. Or check if it's running on a different port

### Scenario B: "Pairing code is invalid or has expired"
**Cause**: Session was cleaned up or code timed out

**Solution**:
1. Get a fresh code by clicking "Connect inside Premiere" again
2. Use it within 15 minutes
3. Check the debug endpoint to see active sessions

### Scenario C: "This pairing code cannot be used (current state: ...)"
**Cause**: You're trying to reuse a code that's already been used or is in wrong state

**Solution**:
1. Click "Connect inside Premiere" again to get a new code
2. Only use each code once

## How It Works (Technical)

1. **User clicks "Connect inside Premiere"** → Frontend requests new session from backend
2. **Backend creates session** → Generates unique pairing code, stores in `_pairing_codes` dict
3. **Frontend stores port** → Saves backend port in `localStorage` so Premiere extension knows where to find it
4. **User enters code in Premiere** → Sends to `/integrations/premiere/bridge/pair`
5. **Backend validates** → Looks up pairing code, verifies it's in "waiting_for_premiere" state
6. **Pairing succeeds** → Returns command and token for further communication

## Architecture

```
Browser (localhost:5173)
    ↓ (stores port in localStorage)
Premiere Extension (CEP Panel)
    ↓ (reads port from localStorage)
Backend (localhost:8000)
    ├─ /api/* routes (proxied from frontend)
    ├─ /integrations/premiere/bridge/pair (direct from extension)
    ├─ /integrations/premiere/bridge/receipt (direct from extension)
    └─ /integrations/premiere/bridge/debug (troubleshooting)
```

## Files Changed

- `web/src/PremiereCard.tsx` - Now sets `airender_port` in localStorage
- `premiere-bridge/js/panel.js` - Better error messages and port display
- `premiere-bridge/index.html` - Corrected placeholder format
- `app/premiere_bridge.py` - More specific error messages in `pair()` function
- `app/main.py` - Added `/integrations/premiere/bridge/debug` endpoint
