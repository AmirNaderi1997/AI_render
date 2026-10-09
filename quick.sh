#!/bin/bash

# 1. Enable CEP debug mode
defaults write com.adobe.CSXS.12 PlayerDebugMode 1

# 2. Create symlink from AI Render folder
cd ~/Documents/AI_render
ln -s "$(pwd)/premiere-bridge" "$HOME/Library/Application Support/Adobe/CEP/extensions/com.airender.bridge"

# 3. Restart Premiere completely
killall "Adobe Premiere Pro 2025"

echo "DONE"
