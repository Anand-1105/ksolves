import os

# Disable random tool failures during tests so results are deterministic.
os.environ.setdefault('TOOL_FAILURE_RATE', '0')

