import os

# Tests never need a visible window; CI runners on Linux have no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
