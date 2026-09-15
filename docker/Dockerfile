# Spike image v2: REAL Google Chrome, not Playwright's bundled Chromium.
#
# gflow's own gate (browser_manager.is_playwright_chrome_channel_available) accepts
# exactly one Linux path for channel="chrome": /opt/google/chrome/chrome. That is where
# the google-chrome-stable .deb installs, so this image satisfies gflow's detector and
# not merely Playwright's.
# 3.14, not 3.11. 3.11 is only the project's requires-python FLOOR — a reason for the
# minimum SUPPORTED version, not for a runtime image.
#
# CI's matrix is ["3.11","3.12","3.13"], so 3.14 is not covered by the suite. That matters
# less here than it looks: a container pins its interpreter, so this is deterministic
# rather than an ambient version that might surprise someone. The gap is closed by
# verifying the image's actual runtime contract below rather than by staying on an older
# interpreter — see docker/README.md § "Verified on this image".
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    GFLOW_CLI_UPDATE_CHECK=false \
    GFLOW_CLI_HOME=/data/gflow

RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb xauth ca-certificates curl gnupg \
 && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list \
 && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir gflow-cli==0.75.0

VOLUME ["/data"]
WORKDIR /data
CMD ["gflow", "--help"]
