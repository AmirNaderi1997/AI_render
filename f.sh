#!/bin/bash
# Find what's using your disk (needs a minute)
sudo du -sh /Users/amirhossein/Library/Containers/com.docker.docker/ 2>/dev/null
sudo du -sh /Users/amirhossein/Documents/* 2>/dev/null | sort -rh | head -10
sudo du -sh /Users/amirhossein/Library/* 2>/dev/null | sort -rh | head -10
