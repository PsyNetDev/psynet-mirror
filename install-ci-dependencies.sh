# Chrome, ChromeDriver, and demo deps are installed in the Docker image via
# Dallinger constraints extras.
# Only install PsyNet itself, which needs the mounted volume at runtime.
PSYNET_WORKSPACE=${PSYNET_WORKSPACE:-/root/workspaces/PsyNet}
uv pip install --no-cache --system --no-deps -e "$PSYNET_WORKSPACE"
