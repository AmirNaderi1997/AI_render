# Proof: JSON edit plan -> MLT -> MP4

Ran on 2026-09-29 in a Linux container (MLT/melt 7.22, FFmpeg 6 with libass).

```bash
./make_media.sh                       # regenerates the synthetic test media in media/
python3 build_mlt.py plan.json        # writes project.mlt + captions.ass
melt project.mlt -consumer avformat:exports/proof.mp4 vcodec=libx264 crf=20 preset=veryfast acodec=aac ab=192k
```

Result: 12.7 s raw (1080x1920, 30 fps) -> 7.3 s reel, rendered in ~24 s on CPU.

| Feature | How it was done in MLT | Verified |
|---|---|---|
| Cut / pause removal | `playlist` entries with `in`/`out` (keep ranges from `ffmpeg silencedetect`) | yes, 3 pauses removed |
| Zoom / punch-in | `affine` filter, keyframed `transition.rect` | yes (115% and 100->110%) |
| Subtitles | `captions.ass` burned via `avfilter.subtitles` (libass) on the tractor | yes, 3 styles |
| B-roll | second video track + `affine` transition | yes, 3.8-5.6 s |
| Music + ducking | music track, `volume` filter with keyframed `level` (dB), `avfilter.afade` out | yes |
| SFX | third audio track with blanks, `mix` transitions (`sum=1`) | yes |
| Export MP4 | `avformat` consumer, H.264 + AAC | yes |

Not verified in the container: Whisper (model download blocked by the container's network policy; the test
video's speech was generated with espeak-ng and pauses were found with FFmpeg), and opening the file in the
Kdenlive GUI (no desktop in the container). Both are stage 1 checks on the user's own machine.

Gotcha found: `<producer>` elements must be declared outside `<playlist>` elements, otherwise MLT treats
them as extra playlist items (the first render was 9.6 s with B-roll at the start).
