# AI Render Premiere Bridge

This CEP panel is the in-Premiere half of AI Render's authenticated bridge for
Premiere Pro 25.0–25.5. It is intentionally separate from the macOS
`/usr/bin/open` fallback.

## Development installation

Adobe requires CEP extensions to be signed for normal distribution. Package and
sign this directory as a ZXP for production. Do not disable macOS Gatekeeper and
do not treat an unsigned development load as a distributable installation.

After installing the signed extension, open **Window → Extensions → AI Render
Bridge**. In AI Render, link the exact clean job project, make a current final
render, press **Connect inside Premiere**, and enter the displayed one-time code
in the panel. The code expires after ten minutes and authorizes one job only.

The panel calls the local backend at `http://127.0.0.1:8000`, executes the
command inside Premiere, and posts a structured receipt. AI Render reports
complete, partial, and failed outcomes separately.

Premiere's CEP DOM can confirm a newly created caption track from the return
value of `createCaptionTrack`, but it does not expose an API for enumerating an
existing caption track. A reconnect therefore inspects the project, sequence,
active Timeline, track counts, exact media paths, and rendered-reference
placement without creating another caption track. Caption persistence remains
explicitly unverified and the reconnect receipt is `partial`; it is never
promoted to success merely because caption creation was skipped.

Premiere 25.6+ should use a UXP implementation of the same protocol. Adobe's
UXP `Project` APIs required by this workflow begin at 25.6; the installed 25.3
host therefore uses CEP/ExtendScript.

## Local Development Setup

1. **Enable unsigned extensions** (one-time setup):
   ```bash
   defaults write com.adobe.CSXS.12 PlayerDebugMode 1
   ```

2. **Create CEP extension symlink** (from AI Render project root):
   ```bash
   ln -s "$(pwd)/premiere-bridge" "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"
   ```

3. **Restart Premiere**

4. **Verify in Premiere**: Window → Extensions → AI Render Bridge

## Troubleshooting

### "EvalScript error" in the bridge panel

This error means the CEP panel tried to execute the JSX bridge script but it failed. 

**Solutions:**
- Restart Premiere completely (quit and reopen)
- Verify the extension symlink exists: `ls -l ~/Library/Application\ Support/Adobe/CEP/extensions/ir.airender.premiere.bridge`
- Check that PlayerDebugMode is enabled: `defaults read com.adobe.CSXS.12 PlayerDebugMode`
- Try running: `defaults write com.adobe.CSXS.12 PlayerDebugMode 1` again
- Make sure you're using Premiere Pro 25.0 or later
- Try creating a new Premiere project with a clean state

### "Pairing code is invalid, expired, or already used"

The pairing code has a 15-minute expiration and can only be used once.

**Solutions:**
- Click "Connect inside Premiere" again in AI Render to get a fresh code
- Make sure the backend is running on port 8000
- Check that you're entering the code within 15 minutes
- Verify the code format: XXXX-XXXX-XXXX (12 hex digits)

### CEP panel shows "Waiting for a pairing code"

The panel loaded successfully but hasn't received a pairing code yet.

**Next step**: Click "Connect inside Premiere" in the AI Render web interface.
