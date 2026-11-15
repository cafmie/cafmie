"""Save-folder sync with freshness checks before overwrite."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Optional

from .models import FreshnessAction, SaveFileDecision


ProgressCb = Optional[Callable[[float, str], None]]


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            files.append(Path(dirpath) / name)
    return files


def plan_save_sync(
    source_dir: Path,
    dest_dir: Path,
    policy: str = "newer_wins",
) -> list[SaveFileDecision]:
    """Compare source (incoming) vs dest (local) and decide per-file actions."""
    source_dir = source_dir.expanduser().resolve()
    dest_dir = dest_dir.expanduser().resolve()
    decisions: list[SaveFileDecision] = []

    source_files = {p.relative_to(source_dir).as_posix(): p for p in _iter_files(source_dir)}
    dest_files = {p.relative_to(dest_dir).as_posix(): p for p in _iter_files(dest_dir)} if dest_dir.exists() else {}

    for rel, src in sorted(source_files.items()):
        src_st = src.stat()
        dst = dest_files.get(rel)
        if dst is None:
            decisions.append(
                SaveFileDecision(
                    relative_path=rel,
                    remote_mtime=src_st.st_mtime,
                    remote_size=src_st.st_size,
                    action=FreshnessAction.OVERWRITE,
                    reason="missing locally",
                )
            )
            continue

        dst_st = dst.stat()
        if abs(src_st.st_mtime - dst_st.st_mtime) < 1e-6 and src_st.st_size == dst_st.st_size:
            decisions.append(
                SaveFileDecision(
                    relative_path=rel,
                    local_mtime=dst_st.st_mtime,
                    remote_mtime=src_st.st_mtime,
                    local_size=dst_st.st_size,
                    remote_size=src_st.st_size,
                    action=FreshnessAction.SKIP,
                    reason="identical",
                )
            )
            continue

        if policy == "always_remote":
            action = FreshnessAction.OVERWRITE
            reason = "policy always_remote"
        elif policy == "prompt":
            action = FreshnessAction.PROMPT
            reason = "conflict — needs confirmation"
        else:  # newer_wins
            if src_st.st_mtime > dst_st.st_mtime:
                action = FreshnessAction.OVERWRITE
                reason = "remote newer"
            elif src_st.st_mtime < dst_st.st_mtime:
                action = FreshnessAction.KEEP_LOCAL
                reason = "local newer"
            else:
                # same mtime, different size — prefer remote when syncing in
                action = FreshnessAction.OVERWRITE
                reason = "same mtime, size differs"

        decisions.append(
            SaveFileDecision(
                relative_path=rel,
                local_mtime=dst_st.st_mtime,
                remote_mtime=src_st.st_mtime,
                local_size=dst_st.st_size,
                remote_size=src_st.st_size,
                action=action,
                reason=reason,
            )
        )
    return decisions


def apply_save_sync(
    source_dir: Path,
    dest_dir: Path,
    decisions: list[SaveFileDecision],
    progress: ProgressCb = None,
) -> int:
    """Copy files marked OVERWRITE from source_dir into dest_dir. Returns count copied."""
    source_dir = source_dir.expanduser().resolve()
    dest_dir = dest_dir.expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    to_copy = [d for d in decisions if d.action == FreshnessAction.OVERWRITE]
    total = max(len(to_copy), 1)
    copied = 0
    for idx, decision in enumerate(to_copy):
        src = source_dir / decision.relative_path
        dst = dest_dir / decision.relative_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
        if progress:
            progress((idx + 1) / total * 100.0, f"Synced {decision.relative_path}")
    if progress:
        progress(100.0, f"Synced {copied} file(s)")
    return copied


def sync_saves(
    source_dir: Path,
    dest_dir: Path,
    policy: str = "newer_wins",
    progress: ProgressCb = None,
) -> tuple[list[SaveFileDecision], int]:
    decisions = plan_save_sync(source_dir, dest_dir, policy=policy)
    # Auto-resolve prompts as keep_local for non-interactive default safety
    resolved: list[SaveFileDecision] = []
    for d in decisions:
        if d.action == FreshnessAction.PROMPT:
            resolved.append(d.model_copy(update={"action": FreshnessAction.KEEP_LOCAL, "reason": d.reason + " (default keep local)"}))
        else:
            resolved.append(d)
    count = apply_save_sync(source_dir, dest_dir, resolved, progress=progress)
    return resolved, count
