"""Host-side proof that the internal services have no route to the internet.

Needs the docker CLI and the running stack, so it is skipped inside the analytics container
and when the stack is down. Run it with::

    STACK_SMOKE=1 analytics/.venv/bin/pytest analytics/tests/test_isolation.py

``STACK_SMOKE=1`` turns "stack not running" into a failure instead of a skip.
"""

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.docker

PROJECT = "moodle-local-stack"
OFFLINE = ["moodle", "cron", "db", "analytics", "ollama"]
EXPECTED_NETWORKS = {
    "moodle": {"backend", "web"},
    "cron": {"backend"},
    "db": {"backend"},
    "analytics": {"backend"},
    "ollama": {"backend"},
    "proxy": {"frontend", "web"},
}
# Internal peer used as a positive control, so a missing tool cannot look like a blocked route.
PEER = {"db": ("analytics", 8000)}
DEFAULT_PEER = ("db", 3306)


def _docker(*args, timeout=30):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _container(service):
    out = _docker(
        "ps", "-aq",
        "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", f"label=com.docker.compose.service={service}",
    )
    ids = out.stdout.split()
    return ids[0] if ids else None


def _exec(service, *command):
    cid = _container(service)
    return _docker("exec", cid, *command, timeout=30).returncode


@pytest.fixture(scope="module", autouse=True)
def stack():
    required = os.environ.get("STACK_SMOKE") == "1"
    problem = None
    if shutil.which("docker") is None:
        problem = "docker CLI not available"
    else:
        try:
            if _docker("info", timeout=15).returncode != 0:
                problem = "docker daemon not reachable"
            elif any(_container(s) is None for s in EXPECTED_NETWORKS):
                problem = f"stack {PROJECT} is not running"
        except (OSError, subprocess.TimeoutExpired):
            problem = "docker daemon not reachable"
    if problem:
        if required:
            pytest.fail(problem)
        pytest.skip(problem)


@pytest.mark.parametrize("service", OFFLINE)
def test_internal_dns_works_but_internet_dns_does_not(service):
    peer, _ = PEER.get(service, DEFAULT_PEER)
    assert _exec(service, "timeout", "5", "getent", "hosts", peer) == 0, "control: internal DNS must work"
    assert _exec(service, "timeout", "5", "getent", "hosts", "example.com") != 0


@pytest.mark.parametrize("service", OFFLINE)
def test_internal_tcp_works_but_direct_internet_ip_does_not(service):
    peer, port = PEER.get(service, DEFAULT_PEER)
    assert _exec(service, "timeout", "5", "bash", "-c", f"</dev/tcp/{peer}/{port}") == 0, "control: internal TCP must work"
    assert _exec(service, "timeout", "5", "bash", "-c", "</dev/tcp/1.1.1.1/443") != 0


@pytest.mark.parametrize("service", sorted(EXPECTED_NETWORKS))
def test_network_membership(service):
    out = _docker(
        "inspect", "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}", _container(service)
    ).stdout.split()
    assert {n.removeprefix(f"{PROJECT}_") for n in out} == EXPECTED_NETWORKS[service]


@pytest.mark.parametrize("network,internal", [("backend", "true"), ("web", "true"), ("frontend", "false")])
def test_network_internal_flag(network, internal):
    out = _docker("network", "inspect", "-f", "{{.Internal}}", f"{PROJECT}_{network}").stdout.strip()
    assert out == internal


def test_only_proxy_publishes_a_port_on_loopback():
    published = []
    ids = _docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}").stdout.split()
    for cid in ids:
        out = _docker(
            "inspect", "-f",
            "{{index .Config.Labels \"com.docker.compose.service\"}} "
            "{{range $p, $l := .NetworkSettings.Ports}}{{range $l}}{{.HostIp}}:{{.HostPort}} {{end}}{{end}}",
            cid,
        ).stdout.split()
        published += [(out[0], binding) for binding in out[1:]]
    assert published, "the proxy must publish the Moodle port"
    assert {service for service, _ in published} == {"proxy"}
    assert all(binding.startswith("127.0.0.1:") for _, binding in published)
