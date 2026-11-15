"""UDP LAN peer discovery (same-subnet broadcast)."""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Callable, Optional

from .models import DeviceRole, PeerInfo, utc_now


DISCOVERY_MAGIC = "pc-transfer-v1"
BROADCAST_INTERVAL_SEC = 2.0
PEER_TTL_SEC = 8.0


class DiscoveryService:
    def __init__(
        self,
        device_id: str,
        device_name: str,
        role: DeviceRole,
        http_port: int,
        discovery_port: int = 8788,
        on_peers_changed: Optional[Callable[[list[PeerInfo]], None]] = None,
    ) -> None:
        self.device_id = device_id
        self.device_name = device_name
        self.role = role
        self.http_port = http_port
        self.discovery_port = discovery_port
        self.on_peers_changed = on_peers_changed
        self._peers: dict[str, PeerInfo] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        t_listen = threading.Thread(target=self._listen_loop, name="discovery-listen", daemon=True)
        t_announce = threading.Thread(target=self._announce_loop, name="discovery-announce", daemon=True)
        t_prune = threading.Thread(target=self._prune_loop, name="discovery-prune", daemon=True)
        self._threads = [t_listen, t_announce, t_prune]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        self._threads = []

    def list_peers(self) -> list[PeerInfo]:
        with self._lock:
            return sorted(self._peers.values(), key=lambda p: p.name.lower())

    def _payload(self) -> bytes:
        body = {
            "magic": DISCOVERY_MAGIC,
            "device_id": self.device_id,
            "name": self.device_name,
            "role": self.role.value,
            "port": self.http_port,
        }
        return json.dumps(body).encode("utf-8")

    def _announce_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            while not self._stop.is_set():
                try:
                    sock.sendto(self._payload(), ("255.255.255.255", self.discovery_port))
                except OSError:
                    pass
                self._stop.wait(BROADCAST_INTERVAL_SEC)
        finally:
            sock.close()

    def _listen_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.discovery_port))
        except OSError:
            # Port busy — still allow manual peer connect via UI
            sock.close()
            return
        sock.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._handle_packet(data, addr[0])
        finally:
            sock.close()

    def _handle_packet(self, data: bytes, host: str) -> None:
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if msg.get("magic") != DISCOVERY_MAGIC:
            return
        device_id = msg.get("device_id")
        if not device_id or device_id == self.device_id:
            return
        try:
            role = DeviceRole(msg.get("role", "main"))
            peer = PeerInfo(
                device_id=device_id,
                name=str(msg.get("name") or "Peer"),
                role=role,
                host=host,
                port=int(msg.get("port") or self.http_port),
                last_seen=utc_now(),
            )
        except (TypeError, ValueError):
            return

        changed = False
        with self._lock:
            prev = self._peers.get(device_id)
            if prev is None or prev.name != peer.name or prev.host != peer.host or prev.port != peer.port:
                changed = True
            self._peers[device_id] = peer
        if changed and self.on_peers_changed:
            self.on_peers_changed(self.list_peers())

    def _prune_loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            removed = False
            with self._lock:
                stale = [
                    pid
                    for pid, peer in self._peers.items()
                    if now - peer.last_seen.timestamp() > PEER_TTL_SEC
                ]
                for pid in stale:
                    del self._peers[pid]
                    removed = True
            if removed and self.on_peers_changed:
                self.on_peers_changed(self.list_peers())
            self._stop.wait(2.0)

    def inject_peer_for_tests(self, peer: PeerInfo) -> None:
        with self._lock:
            self._peers[peer.device_id] = peer
