"""Curricarta: curricula captured, docked and linked after Curriculum-Kern 1.0."""

import os

__version__ = "0.1.0"
# The commit the image was built from (deploy/api.Dockerfile, build argument REVISION): a build
# fact, not a setting; outside an image "unknown"
__revision__ = os.environ.get("CURRICARTA_REVISION", "unknown")
