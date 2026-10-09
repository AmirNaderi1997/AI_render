# Premiere Pro desktop handoff

## In-Premiere bridge

AI Render now defines a versioned, authenticated bridge protocol in
`app/premiere_bridge.py`. Premiere Pro 25.0–25.5 uses the CEP panel in
`premiere-bridge/`; Adobe's equivalent UXP Project APIs begin at Premiere 25.6.
The bridge is paired with a one-time, job-scoped code that expires after ten
minutes. A completed receipt requires strict, typed observations for the exact
active project, imported or found sequence, active Timeline, rendered-reference
import and absence from the editable Timeline, caption import/track placement,
zero duplicates, and a successful native save result. Complete, partial, and
failed receipts are never collapsed into a generic “sent” result.

The bridge requires an already linked, current clean `.prproj` and a current
final render. This keeps project selection explicit and prevents a command from
mutating whichever unrelated project happens to be active. Repeated operations
reuse a current hash-bound receipt and ask the panel to verify/open/save without
re-importing the sequence, render, or captions. If any artifact or the native
project bytes change, the receipt is no longer current.

CEP does not expose an existing-caption-track enumeration API. On reconnect the
panel re-inspects all state CEP can observe and does not create a duplicate
caption track blindly. It reports caption persistence as unverified, which
makes that reconnect `partial` rather than manufacturing a completed receipt.

The existing handoff below remains the no-plugin fallback.

AI Render detects the local Premiere app from its macOS bundle metadata. The Plan Review and Render cards report the FCP7 XML package, current final MP4, and linked native project separately. Desktop actions require a loopback request and a local browser origin. The browser supplies a fixed action name; the backend resolves files from the job record and rejects files outside the job directory or through symlink escapes.

The editable plan is `project_premiere.xml`, not a `.prproj`. The generated SRT remains a separate Premiere import. AI Render never writes Adobe's native project format. Create a clean, dedicated Premiere project, import the XML, import the final MP4 as a separate rendered reference, then import the SRT and place it on the editable sequence as a caption track. Save as `ai-render-{job_id}-clean.prproj`, then use **Link clean Premiere project**. Linking is rejected until that exact job-local filename exists. AI Render records plan, XML, SRT, and final-render hashes; a changed hash marks the link outdated.

`Open plan + rendered video` never injects media into an active project. With a current link it opens that exact `.prproj`; with no link it opens Premiere and reveals the job folder with manual setup instructions; with stale hashes it reveals the updated files and asks the user to refresh them in Premiere explicitly. Process launch is only a launch request, not an import receipt. Repeating the current-link action only opens the linked project again.

## Fresh job acceptance, 2026-10-04

Job `7d8424669e18` was created from `MYVIDEO.mp4`, generated a new Edit Plan, and rendered `exports/v1.mp4` as a final output. `ffprobe` reported 1080×1920, 30 fps, 31.573 seconds. The desktop capability endpoint reported Premiere 25.3.0.

Observed in Premiere's project panel after AI Render handoff: an `AI Render editable sequence` item, `v1.mp4` as a separate media item, and `premiere_captions.srt` as a separate item. Premiere saved `ai-render-7d8424669e18.prproj` in the job folder; after **Close Project**, AI Render reopened that exact project and those items were still visible. The linked indicator survived a browser reload and backend reload. A controlled change to `plan.json` showed a stale package and outdated project warning; the original bytes were restored and status returned to ready/final/linked.

The clean project `ai-render-7d8424669e18-clean.prproj` was created in Premiere from an empty Project panel. It now contains the imported editable sequence, its source media item, `v1.mp4` as a separate item, and `premiere_captions.srt` as an SRT item, with no unrelated pre-existing items. AI Render links this clean project and reports it current. The sequence has not yet been opened in the Timeline, and the SRT has not been placed on a caption track. Timeline properties, transition observations, captions, relinking, close/reopen, and the required screenshot set remain unverified. No hash-bound native-verification record was created.
