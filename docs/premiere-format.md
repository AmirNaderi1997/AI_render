# Premiere Pro interchange package

AI Render exports a Final Cut Pro 7 XML Interchange (`xmeml` v5) document for
Premiere import. It does **not** create or reverse-engineer Adobe's private
`.prproj` format. Import `project_premiere.xml` in Premiere, relink media if it
has moved, then save the imported project from Premiere as `.prproj`.

The ZIP contains the XML, UTF-8 `premiere_captions.srt`, `README.txt`,
`premiere_transition_report.json`, and the referenced source, B-roll, music,
and narration/SFX media under `media/`. XML media paths are relative to the ZIP
root; extract the entire archive before importing the XML. The report filename remains for compatibility;
the file is now the complete package compatibility manifest. Plan Review also
offers separate XML, SRT, ZIP, and manifest downloads.

## Edit and timing behavior

The Edit Plan JSON remains the authority. Each source segment is rounded once
to output frames, and each rendered boundary overlap shortens the output by its
`duration_frames`:

`output_frames = sum(segment_frames) - sum(transition_duration_frames)`

Hard cuts import as exact cuts. Crossfades import as editable Cross Dissolve
video transitions plus editable `Cross Fade (+3dB)` audio transitions.
Historical native verification on 2026-10-04 used Premiere Pro 25.3.0 and
established the general mapping capability for hard cuts, crossfades, and the
directional fallback on earlier short/full sequences. That evidence is exposed
as `capability_classification`; it does not verify a newly generated package.
The separate `current_artifact_verification` remains `unverified` until the
exact package has been imported, visibly inspected, saved, reopened, and tied
to its hashes.

Directional transitions retain direction and intensity in the Edit Plan and
render exactly through MLT into the MP4. Premiere 25.3.0 replaces an FCP7
`Slide` mapping with Cross Dissolve, so AI Render deliberately exports that
editable fallback and reports the requested movement as rendered-only in
Premiere.

Boundary zoom is a first-class `BoundaryTransition`, not a segment visual
effect. MLT animates a centered scale/opacity move using the requested mode and
scale; the existing Reel/Story/Post caps are 12/10/8 frames. Too-short adjacent
segments fall back to a hard cut during planning. The Premiere XML currently
proposes a Cross Dissolve and retains the requested zoom mode and scale in the
manifest. Since this zoom-boundary mapping has not passed native import, save,
and reopen verification, the manifest classifies it as `unverified`, not as an
editable fallback.
The MP4 is the visual authority for zoom until a mapping passes import, save, and
reopen inspection.

Kdenlive receives the same MLT boundary overlap graph, including boundary zoom.
It is not a separate plan or renderer authority.

## Captions and effects

Captions are output-timeline SRT sidecars encoded as UTF-8. Import the XML, then
import `premiere_captions.srt` as captions in Premiere. The SRT preserves the
caption text and timing, including Persian text, but it does not encode AI
Render's font, weight, outline, placement, or RTL styling. Those presentation
choices remain authoritative in the rendered MP4. Native import/save/reopen
verification of the Persian fixture remains unverified until captured in
Premiere.

Segment-level `visual_effects` and legacy segment zoom stay in the rendered MP4.
AI Render does not currently write Premiere effect filters for them, so the
manifest classifies each planned effect as `rendered_only`. No effect mapping is
claimed based only on generated XML.

## Media references and manifest

The XML references source media by absolute `file:` URL. The ZIP does not embed
source media. Keep the source at that path or use Premiere's normal relink flow
when moving the package. Relinking and portability have not yet passed a fresh
native acceptance check.

`premiere_transition_report.json` includes schema/report version, plan identity
and fingerprint, creation time, sequence geometry/frame count/duration, file
roles, one entry per transition, per-caption timing and delivery, every planned
segment effect, source-reference/relink guidance, warnings, native verification
state, and an overall result. Legacy `classification` fields remain for existing
clients. Every mapping also exposes both `capability_classification` and
`current_artifact_verification`, so Plan Review can distinguish “Previously
verified mapping” from “Verified in this package.” A historical verification
date is never presented as the date of a newly generated package.
Classifications mean:

- `exact_editable`: the requested feature is represented and has native
  import-save-reopen evidence.
- `editable_fallback`: native import evidence confirms that Premiere receives
  an editable substitute while the requested behavior remains in the rendered
  MP4. Candidate XML mappings without that evidence remain `unverified`.
- `sidecar_editable`: editable data is provided in a separate file to import.
- `rendered_only`: the visual feature is retained in the MP4, not as an editable
  Premiere effect.
- `unsupported`: no package representation is available.
- `unverified`: native behavior has not been inspected through import, save,
  and reopen.

Every warning and mapping is also displayed in Plan Review before download.
The rendered MP4 is visually authoritative for every fallback, sidecar styling
gap, rendered-only feature, or unverified mapping.

## Native verification record

Baseline scope on 2026-10-04: existing short and full FCP7 XML packages were
reported imported in Adobe Premiere Pro 25.3.0; hard cuts and crossfades were
exact and directional transitions became Cross Dissolves. This implementation's
zoom, Persian SRT import/save/reopen, representative effect fixtures, fresh-job
native sequences, and relink workflow require separate current evidence and are
not covered by that baseline record.

Current-package observations live in the optional local-only
`premiere_native_verification.json` record. AI Render does not accept this record
from the browser or through a certification API. The writer validates the
operator-observed sequence, every planned boundary, caption/relink/effect
observations, save/reopen state, existing `.prproj`, and evidence screenshot
paths. It binds the record to the job ID plus SHA-256 digests of `plan.json`, the
XML, and the SRT. Any later plan, XML, or SRT change makes the manifest report
the record as `invalidated`; it cannot remain verified through a stale global
date or an unrelated project file.

The overall result cannot become `current_artifact_verified_with_limitations`
unless all required current-artifact component observations are present, the
observed frame count and geometry match the plan, save/reopen is verified, and
the relink exercise is verified. Otherwise it remains
`awaiting_current_artifact_verification`.
