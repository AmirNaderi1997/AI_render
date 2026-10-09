#!/bin/bash
# 1. Force-quit Docker completely
osascript -e 'quit app "Docker"'
killall -9 com.docker.backend 2>/dev/null
killall -9 Docker 2>/dev/null

# 2. Wipe Docker's corrupted state (keeps your images/containers gone, but they need rebuilding anyway)
rm -rf ~/Library/Containers/com.docker.docker
rm -rf ~/Library/Group\ Containers/group.com.docker
rm -rf ~/.docker

# 3. Reopen Docker Desktop
open -a Docker
