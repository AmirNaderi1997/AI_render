#!/bin/bash
open -a Docker
# Wait 30 seconds for Docker to start, then:
cd ~/Documents/AI_render
docker compose build --progress=plain
