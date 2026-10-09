# AI Render Premiere Bridge - Complete Setup Guide

## Overview

The AI Render Premiere Bridge is a CEP (Common Extensibility Platform) extension that automates importing sequences, renders, and captions into Premiere Pro. This guide covers complete setup and troubleshooting.

## System Requirements

- **Premiere Pro**: 25.0 - 25.5 (CEP-based, not UXP)
- **macOS**: 10.13+ (Intel or Apple Silicon)
- **AI Render Backend**: Must be running on localhost:8000

## One-Time Setup (5 minutes)

### Step 1: Enable CEP Debug Mode

This allows unsigned extensions to run. You only need to do this once.

```bash
defaults write com.adobe.CSXS.12 PlayerDebugMode 1
```

**Verify it worked:**
```bash
defaults read com.adobe.CSXS.12 PlayerDebugMode
# Should output: 1
```

### Step 2: Install the Extension Symlink

From your AI Render project directory, run:

```bash
ln -s "$(pwd)/premiere-bridge" "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"
```

**Verify the symlink:**
```bash
ls -l "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"
# Should show: ir.airender.premiere.bridge -> /path/to/ai_render/premiere-bridge
```

### Step 3: Restart Premiere

Quit Premiere completely and reopen it.

```bash
killall "Adobe Premiere Pro 2025"
# Wait a few seconds, then reopen Premiere
```

### Step 4: Verify Extension is Loaded

In Premiere: **Window → Extensions → AI Render Bridge**

You should see the panel with:
- Title: "AI Render Bridge"
- Input field: "Pairing Code"
- Status: "Waiting for a pairing code."

**If the panel doesn't appear:**
- Go to Window → Extensions → check if "AI Render Bridge" is in the list
- If not listed, the symlink setup failed - check Step 2
- Try restarting Premiere again

## Using the Bridge

### Complete Workflow

1. **In AI Render (web interface)**:
   - Go to a completed render job
   - Click **"Link clean Premiere project"** (one time per job)
   - Click **"Connect inside Premiere"**
   - Copy or note the pairing code (e.g., `A1B2-C3D4-E5F6`)
   - Code expires in 15 minutes

2. **In Premiere**:
   - Open Window → Extensions → AI Render Bridge
   - Paste the pairing code
   - Click "Connect and Apply"
   - Wait for confirmation

3. **What the Bridge Does**:
   - ✅ Opens your linked Premiere project
   - ✅ Imports the edited sequence
   - ✅ Imports the rendered video reference
   - ✅ Imports the captions SRT
   - ✅ Places captions on the sequence (if API available)
   - ✅ Saves the project

## Troubleshooting

### Scenario 1: Panel Shows "EvalScript error"

The CEP panel loaded but the JSX bridge script failed to execute.

**Solutions (try in order):**

1. **Restart Premiere** (complete quit and reopen)
   ```bash
   killall "Adobe Premiere Pro 2025"
   open /Applications/Adobe\ Premiere\ Pro\ 2025/Adobe\ Premiere\ Pro\ 2025.app
   ```

2. **Check PlayerDebugMode is enabled**:
   ```bash
   defaults write com.adobe.CSXS.12 PlayerDebugMode 1
   ```

3. **Close and reopen the bridge panel** (Window → Extensions → AI Render Bridge)

4. **Create a new Premiere project** (sometimes works if project is corrupted):
   - File → New Project
   - Create a new, empty project
   - Try linking a clean project again

5. **Check Premiere version**:
   - Premiere → About Adobe Premiere Pro
   - Should be 25.0.x or later
   - If older, update Premiere

### Scenario 2: "Cannot reach AI Render on http://127.0.0.1:8000"

The extension can't connect to the backend.

**Solutions:**

1. **Start the backend**:
   ```bash
   cd ~/Documents/AI_render
   python -m uvicorn app.main:app --port 8000
   ```

2. **Verify backend is accessible**:
   ```bash
   curl http://localhost:8000/
   # Should return: {"ok":true,"service":"rafiei-ai-editor",...}
   ```

3. **Check port 8000 is not in use**:
   ```bash
   lsof -i :8000
   # If something else is using it, stop that process or use a different port
   ```

4. **Update the port in localStorage**:
   - Open browser DevTools (F12) on http://localhost:5173
   - Run: `localStorage.setItem("airender_port", "8000")`
   - Reload the Premiere extension

### Scenario 3: "Pairing code is invalid, expired, or already used"

The code was rejected.

**Possible causes:**

- ❌ Code expired (15 minute limit)
- ❌ Code was already used once
- ❌ Wrong code entered
- ❌ Pairing in a different browser tab or project

**Solutions:**

1. **Get a fresh code**: Click "Connect inside Premiere" again in AI Render
2. **Use it within 15 minutes**: Time starts when you click the button
3. **Each code is one-time use**: After successful pairing, that code is consumed
4. **Verify code format**: Should be `XXXX-XXXX-XXXX` (12 hex digits)

### Scenario 4: Panel doesn't appear in Window → Extensions menu

The extension symlink failed.

**Solutions:**

1. **Check the symlink exists**:
   ```bash
   ls -l "$HOME/Library/Application Support/Adobe/CEP/extensions/" | grep airender
   ```

2. **If missing, recreate it**:
   ```bash
   cd ~/Documents/AI_render
   ln -s "$(pwd)/premiere-bridge" "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"
   ```

3. **Ensure correct permissions**:
   ```bash
   chmod 755 "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"
   ```

4. **Restart Premiere**:
   ```bash
   killall "Adobe Premiere Pro 2025"
   ```

### Scenario 5: Some items failed to import (Captions, Render, etc.)

The bridge completed but some operations failed.

**Check the error message** - it will say what failed:

- **Sequence import failed**: XML file might be corrupted; regenerate from AI Render
- **Render import failed**: MP4 file path might be wrong; check it exists
- **Captions import failed**: SRT file might be missing; regenerate from AI Render
- **Caption track creation failed**: Your Premiere version might not support `createCaptionTrack` API; drag SRT to Caption track manually

## Advanced Debugging

### Check Active Bridge Sessions

The backend maintains a debug endpoint. Visit in your browser:

```
http://localhost:8000/integrations/premiere/bridge/debug
```

Shows:
- Active sessions
- Session state (waiting_for_premiere, paired, completed, etc.)
- Time until expiration
- Whether pairing code exists

**Example output:**
```json
{
  "active_sessions": [
    {
      "operation_id": "xyz123...",
      "job_id": "0513ce5a741a",
      "state": "waiting_for_premiere",
      "expires_in_seconds": 847,
      "pairing_code_exists": true
    }
  ],
  "total_sessions": 1
}
```

### Check Premiere Extension Logs

Adobe stores CEP logs at:
```
~/Library/Logs/Adobe/CSXS/
```

Check for errors:
```bash
tail -f ~/Library/Logs/Adobe/CSXS/*.log
```

### Verify Backend Health

```bash
curl -s http://localhost:8000/ | jq
# Should return: {"ok":true,"service":"rafiei-ai-editor","stage":3}
```

### Test the Full Pairing Flow Manually

1. **Create a session**:
   ```bash
   curl -X POST http://localhost:8000/api/jobs/0513ce5a741a/premiere/bridge/session \
     -H "Content-Type: application/json" \
     -d '{"force_refresh": false}' | jq
   ```

2. **Use the pairing code**:
   ```bash
   curl -X POST http://localhost:8000/integrations/premiere/bridge/pair \
     -H "Content-Type: application/json" \
     -d '{"pairing_code": "ABCD-EFGH-IJKL", "bridge": {}}'
   ```

## FAQs

**Q: Can I use the bridge multiple times on the same project?**
A: Yes! Each time you click "Connect inside Premiere", you get a new pairing code.

**Q: What if my Premiere project gets corrupted?**
A: The bridge doesn't modify the original Premiere project files. It only imports into the open project. If something goes wrong, close without saving and try again.

**Q: Can I use this with older Premiere versions?**
A: No, this requires Premiere Pro 25.0+. Earlier versions would need a UXP-based implementation.

**Q: Why does captions sometimes say "not placed"?**
A: Premiere's CEP API can't verify caption track placement after creation. You may need to manually drag the SRT to a caption track if auto-placement doesn't work.

**Q: How long does pairing take?**
A: Usually 10-30 seconds depending on file sizes and your system speed.

## Getting Help

If you're stuck:

1. Check the error message carefully - it usually tells you what to do
2. Verify all setup steps above are complete
3. Try restarting Premiere completely (not just closing the panel)
4. Check that the backend is running: `curl http://localhost:8000/`
5. Review the debug endpoint output: http://localhost:8000/integrations/premiere/bridge/debug

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ macOS / Premiere Pro 25.x                          │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Premiere CEP Panel                                │
│  ┌──────────────────────────────────────────────┐  │
│  │ AI Render Bridge                             │  │
│  │ ┌────────────────────────────────────────┐  │  │
│  │ │ index.html + panel.js                  │  │  │
│  │ │ (HTML/JavaScript CEP panel UI)         │  │  │
│  │ └────────────────────────────────────────┘  │  │
│  │          ↓ sends pairing code               │  │
│  │          ↓ receives command                 │  │
│  │ ┌────────────────────────────────────────┐  │  │
│  │ │ bridge.jsx (ExtendScript/JSX)          │  │  │
│  │ │ Communicates with Premiere API         │  │  │
│  │ └────────────────────────────────────────┘  │  │
│  │          ↓ executes in Premiere             │  │
│  │          ↓ imports sequence/render/captions│  │  │
│  │          ↓ returns receipt                  │  │  │
│  └──────────────────────────────────────────────┘  │
│                    ↕                               │
│            HTTP REST API (localhost)               │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────────────────────────────────────────┐
│ Backend: AI Render (uvicorn on port 8000)           │
├──────────────────────────────────────────────────────┤
│                                                      │
│  /api/jobs/{id}/premiere/bridge/session             │
│  → Creates pairing session, returns pairing code     │
│                                                      │
│  /integrations/premiere/bridge/pair                 │
│  → Validates pairing code, returns command          │
│                                                      │
│  /jobs/{id}/premiere/bridge/receipt                 │
│  → Accepts execution receipt, stores results        │
│                                                      │
│  /integrations/premiere/bridge/debug                │
│  → Shows active sessions (for troubleshooting)      │
│                                                      │
└──────────────────────────────────────────────────────┘
```

## Files

- `premiere-bridge/index.html` - CEP panel UI
- `premiere-bridge/js/panel.js` - Panel logic and API communication
- `premiere-bridge/jsx/bridge.jsx` - Premiere API integration (ExtendScript)
- `premiere-bridge/CSXS/manifest.xml` - CEP extension definition
- `premiere-bridge/README.md` - Quick reference

---

**Last Updated**: 2026-10-06
**AI Render Version**: 0.1.x
**Tested with**: Premiere Pro 25.0 - 25.5
