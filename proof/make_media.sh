#!/usr/bin/env bash
# Regenerates the synthetic test media used by proof/plan.json (needs ffmpeg; espeak-ng optional for speech).
set -e
cd "$(dirname "$0")" && mkdir -p media exports && cd media
if command -v espeak-ng >/dev/null; then
  espeak-ng -s 150 -w s1.wav "Most people edit reels the hard way."
  espeak-ng -s 150 -w s2.wav "Today I will show you an AI dashboard that does it for you."
  espeak-ng -s 150 -w s3.wav "Follow for more."
else
  for i in 1 2 3; do ffmpeg -y -loglevel error -f lavfi -i "sine=f=$((200*i)):d=2.3" -ar 22050 -ac 1 s$i.wav; done
fi
ffmpeg -y -loglevel error -f lavfi -t 1.2 -i anullsrc=r=22050:cl=mono -f lavfi -t 1.8 -i anullsrc=r=22050:cl=mono -f lavfi -t 2.0 -i anullsrc=r=22050:cl=mono -i s1.wav -i s2.wav -i s3.wav \
  -filter_complex "[0][3][1][4][2][5]concat=n=6:v=0:a=1,aresample=48000[a]" -map "[a]" voice.wav
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 voice.wav)
ffmpeg -y -loglevel error -f lavfi -i "testsrc2=s=1080x1920:r=30:d=$D" -i voice.wav -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest raw.mp4
ffmpeg -y -loglevel error -f lavfi -i "mandelbrot=s=1080x1920:r=30" -t 4 -c:v libx264 -pix_fmt yuv420p broll_dashboard.mp4
ffmpeg -y -loglevel error -f lavfi -i "sine=f=220:d=30,volume=0.3" -f lavfi -i "sine=f=330:d=30,volume=0.2" -filter_complex amix=2 -ar 48000 -ac 2 music.wav
ffmpeg -y -loglevel error -f lavfi -i "anoisesrc=d=0.6:c=pink,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.3,highpass=f=800" -ar 48000 -ac 2 whoosh.wav
rm -f s1.wav s2.wav s3.wav
echo "media ready in $(pwd)"
