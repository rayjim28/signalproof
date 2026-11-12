"""Keep the local HTTP server bound to its expected origin."""

def local_host_allowed(host: str, port: int) -> bool:
    return host in (f"127.0.0.1:{port}", f"localhost:{port}")


def local_origin_allowed(origin: str, port: int) -> bool:
    return not origin or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
