#!/bin/bash
# Remove unrelated project folders (~6.5 GB freed)
rm -rf ~/Documents/mini-ai-builder
rm -rf ~/Documents/builder-for-final-test
rm -rf ~/Documents/breakup
rm -rf ~/Documents/OpenRoute
rm -rf ~/Documents/ChatGPT
rm -rf ~/Documents/3x-ui
rm -rf ~/Documents/like-loveable-for-distruction
rm -rf "~/Documents/clean v2ray builder"
rm -rf "~/Documents/clear v2ray builder"

# Clear caches (~1 GB freed)
rm -rf ~/Library/Caches/*

# Check free space now
df -h /
