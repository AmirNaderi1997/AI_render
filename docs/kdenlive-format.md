# Kdenlive project format used by Stage 1

Evidence: the two KDE-owned Kdenlive 24.11.70 saved files in
[`samples/reference`](../samples/reference/README.md). Both use document
version `1.1`. The exporter copies the topology visible there; it does not
claim this is a complete specification for all Kdenlive versions.

## Graph

- `<mlt producer="main_bin">` has a `<profile>` matching the Edit Plan's
  1080×1920, 30 fps, square-pixel canvas. Its `root` and all media `resource`
  properties resolve to absolute paths.
- Each imported asset has a `<chain>` with a real media service, `resource`,
  `length`, stream indices, `kdenlive:id`, `kdenlive:clip_type` (0 video, 1
  audio), `kdenlive:duration`, and other bin identification properties.
- A black color producer feeds sequence track 0. Four timeline tracks follow:
  A2, A1, V1, V2 in the sequence's physical MLT order. Each logical track is
  a `<tractor>` with two child playlists. Both audio playlists and their
  tractor have `kdenlive:audio_track=1`; their child tracks hide video.
  Video child tracks hide audio. The second lane is empty until Kdenlive
  needs it for overlap/mix edits.
- Playlist `<entry>` elements carry the bin `kdenlive:id`, source in/out,
  and per-clip filters. V1's consecutive entries are the cuts; its affine
  filters retain the render MLT's zoom keyframes and identify as Kdenlive's `affine` effect.
  V2 blanks and entries place B-roll at output-timeline times. A1 keeps the
  music volume keyframes and fade. A2 places SFX after output-timeline blanks.
- A sequence `<tractor>` has a UUID as its ID, sequence properties, the black
  producer and four track tractors. It has `mix` transitions from the black
  track to both audio tracks (`sum=1`, `accepts_blanks=1`) and `qtblend`
  transitions to the video tracks. These are the internal compositions seen
  in the saved reference files. The top-level project tractor has
  `kdenlive:projectTractor=1` and points to the sequence.
- `<playlist id="main_bin">` contains document properties, a sequence entry,
  and one entry for each imported source chain. Its UUID, active timeline and
  open-sequence properties match the sequence ID. `docproperties.version=1.1`
  and `docproperties.kdenliveversion=24.11.70` are taken from the references;
  the installed Kdenlive 26.08.1 may resave them when the user edits.

## Captions and limits

The upstream fixtures do not establish a reliable XML representation for a
Kdenlive-editable subtitle track, so this exporter does not add one. The
caption ASS/SRT sidecar files remain beside the project for manual import.
The render MLT still burns captions into its MP4. Importing the sidecars into
Kdenlive and matching the styled output remains unverified.
