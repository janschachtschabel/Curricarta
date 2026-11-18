"""deploy/helm-values.example.yaml: Prometheus scrapes every pod that counts jobs.

The workers sit behind no Service: a PodMonitor finds them by a label. Each worker class exports its own
jobs' counters on its port 9000 alone; a class the PodMonitor misses leaves its kinds without metrics,
and the alerts by kind never fire for them.
"""

import pytest

from tests.deploy.test_helm_values import VALUES, WORKERS


@pytest.mark.parametrize("part", WORKERS)
def test_every_worker_class_is_scraped_by_the_pod_monitor(part: str) -> None:
    monitor = VALUES["monitoring"]["podMonitor"]

    assert monitor["enabled"] is True
    assert monitor["selector"]
    assert monitor["selector"].items() <= VALUES[part]["podLabels"].items()
    assert monitor["port"] == VALUES[part]["probes"]["liveness"]["port"]


def test_the_pod_monitor_selects_no_pod_behind_a_service() -> None:
    # the API is scraped through its Service; a second scrape would count its requests twice
    selector = VALUES["monitoring"]["podMonitor"]["selector"]

    assert not selector.items() <= VALUES["api"].get("podLabels", {}).items()
