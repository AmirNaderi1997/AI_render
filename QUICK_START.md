# Premiere Bridge - Quick Start Checklist

## 🚀 Quick Fix (5 minutes)

### Step 1: Enable CEP Debug Mode
```bash
defaults write com.adobe.CSXS.12 PlayerDebugMode 1
```

### Step 2: Create Extension Symlink
```bash
cd ~/Documents/AI_render
ln -s "$(pwd)/premiere-bridge" "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"
```

### Step 3: Restart Premiere
```bash
killall "Adobe Premiere Pro 2025"
# Then reopen Premiere
```

### Step 4: Verify Panel Loads
- Open Premiere
- Window → Extensions → AI Render Bridge
- Should see "Waiting for a pairing code."

---

## ✅ Test the Bridge

### Terminal 1: Start Backend
```bash
cd ~/Documents/AI_render
.venv/bin/python -m uvicorn app.main:app --port 8000
```

Use the project's virtual environment for every backend start. A global
`uvicorn` may run a different Python installation that does not have the
ElevenLabs or Whisper packages listed in `requirements.txt`.

### Terminal 2: Verify Backend
```bash
curl http://localhost:8000/
# Should return: {"ok":true,"service":"rafiei-ai-editor",...}
```

### Browser: Get Pairing Code
1. Open http://localhost:5173
2. Go to a completed render job
3. Click "Connect inside Premiere"
4. Copy the pairing code (format: ABCD-EFGH-IJKL)

### Premiere: Use Pairing Code
1. Window → Extensions → AI Render Bridge
2. Paste the pairing code
3. Click "Connect and Apply"
4. Wait for completion

---

## 🐛 If Something Goes Wrong

### "EvalScript error"
- Restart Premiere completely
- Close and reopen the bridge panel
- Enable debug: `defaults write com.adobe.CSXS.12 PlayerDebugMode 1`

### "Cannot reach AI Render"
- Verify backend is running: `curl http://localhost:8000/`
- Check port: `lsof -i :8000`
- Port should be 8000

### "Pairing code invalid/expired"
- Code expires in 15 minutes
- Each code can only be used once
- Get a fresh code from AI Render web interface

### Panel doesn't appear
- Verify symlink exists:
  ```bash
  ls "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"
  ```
- Recreate if needed:
  ```bash
  cd ~/Documents/AI_render
  ln -s "$(pwd)/premiere-bridge" "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"
  ```

---

## 📊 Check Status

Visit the debug endpoint to see active sessions:
```
http://localhost:8000/integrations/premiere/bridge/debug
```

Shows:
- Active sessions
- Pairing codes
- Session states
- Time until expiration

---

## 📚 Full Documentation

- **Complete Setup**: See `PREMIERE_BRIDGE_SETUP.md`
- **Troubleshooting**: See `PREMIERE_PAIRING_DEBUG.md`
- **Technical Details**: See `PREMIERE_BRIDGE_FIX_SUMMARY.md`

---

## ✨ What Was Fixed

1. **EvalScript errors** - JSX now has proper error handling
2. **Poor error messages** - Now shows exactly what went wrong
3. **Missing port config** - Port is now stored in localStorage
4. **No debugging** - Added debug endpoint at `/integrations/premiere/bridge/debug`
5. **Unsafe API access** - All Premiere API calls are now protected with try-catch

---

## 🎯 Expected Workflow

```
AI Render Web UI
    ↓ Click "Connect inside Premiere"
    ↓ Get pairing code (expires in 15 min)
    ↓
Premiere Extension
    ↓ Paste code
    ↓ Click "Connect and Apply"
    ↓ [Validating code...]
    ↓ [Pairing with backend...]
    ↓ [Importing sequence...]
    ↓ [Importing render...]
    ↓ [Importing captions...]
    ↓ [Saving project...]
    ↓
Result: ✅ Completed
```

---

**Date**: 2026-10-06
**Version**: 0.1.x
**Status**: Ready to test
