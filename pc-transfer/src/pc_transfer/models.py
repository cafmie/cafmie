"""Shared data models for game profiles, peers, and transfer jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex[:12]


class DeviceRole(str, Enum):
    MAIN = "main"
    HANDHELD = "handheld"


class PeerInfo(BaseModel):
    device_id: str
    name: str
    role: DeviceRole
    host: str
    port: int
    last_seen: datetime = Field(default_factory=utc_now)

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


class SaveFolder(BaseModel):
    id: str = Field(default_factory=new_id)
    label: str = "Saves"
    path: str


class GameProfile(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str
    game_folder: str
    save_folders: list[SaveFolder] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PathCheck(BaseModel):
    path: str
    exists: bool
    is_dir: bool = False
    size_bytes: int = 0
    last_modified: Optional[datetime] = None
    error: Optional[str] = None


class GameVerification(BaseModel):
    game_id: str
    title: str
    game_folder: PathCheck
    save_folders: list[PathCheck]
    ok: bool


class FreshnessAction(str, Enum):
    KEEP_LOCAL = "keep_local"
    OVERWRITE = "overwrite"
    SKIP = "skip"
    PROMPT = "prompt"


class SaveFileDecision(BaseModel):
    relative_path: str
    local_mtime: Optional[float] = None
    remote_mtime: Optional[float] = None
    local_size: Optional[int] = None
    remote_size: Optional[int] = None
    action: FreshnessAction
    reason: str


class TransferKind(str, Enum):
    GAME_ZIP = "game_zip"
    SAVE_SYNC = "save_sync"


class TransferRequest(BaseModel):
    kind: TransferKind
    game_id: str
    direction: str  # "send" | "receive"
    peer_device_id: str
    overwrite_policy: str = "newer_wins"  # newer_wins | prompt | always_remote


class TransferProgress(BaseModel):
    job_id: str
    kind: TransferKind
    stage: str
    percent: float = 0.0
    message: str = ""
    done: bool = False
    error: Optional[str] = None


class AppSettings(BaseModel):
    device_id: str = Field(default_factory=new_id)
    device_name: str = "PC Transfer"
    role: DeviceRole = DeviceRole.MAIN
    http_port: int = 8787
    discovery_port: int = 8788
    transfer_port: int = 8789
    data_dir: str = ""
