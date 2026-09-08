import socket


def allocate(names):
    """One free port per name. All sockets stay bound until every port is picked, so they are distinct."""
    socks = []
    ports = {}
    try:
        for name in names:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            socks.append(s)
            ports[name] = s.getsockname()[1]
    finally:
        for s in socks:
            s.close()
    return ports


def is_held(port):
    """True when something listens on the port."""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0
