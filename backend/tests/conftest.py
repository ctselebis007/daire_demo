import os
import tempfile

os.environ.setdefault("DARE_HOME", tempfile.mkdtemp(prefix="dare-test-"))
