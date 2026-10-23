from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from korpus.application.source_checkout_marker import SOURCE_ROOT_MARKER, marker_matches

GIT = "/usr/bin/git"
SSH_KEYGEN = "/usr/bin/ssh-keygen"
TRUSTED_SIGNERS = (
    b"neuron7x@gmail.com ssh-ed25519 "
    b"AAAAC3NzaC1lZDI1NTE5AAAAIDychTBYoCI1yjVsnnTK7QHWM86YugwtYgMfOTorisHu "
    b"neosynaptex-signing-20260413\n"
)
PACKAGE_RECEIPT = "FULL_SSOT_PACKAGE_RECEIPT.json"
DISTRIBUTION_MANIFEST = "DISTRIBUTION_MANIFEST.json"
CANONICAL_REMOTES = {
    b"git@github.com:neuron7x/KORPUS.git",
    b"https://github.com/neuron7x/KORPUS.git",
}
_NTFS_DOTGIT = re.compile(r"(?:\.git|git~1)[ .]*(?::[\s\S]*)?\Z", re.IGNORECASE)
_NTFS_GITMODULES = re.compile(
    r"(?:\.gitmodules|gitmod~[1-4]|~[1-9][0-9]{6}|g~[1-9][0-9]{5}|"
    r"gi~[1-9][0-9]{4}|gi7~[1-9][0-9]{3}|gi7e~[1-9][0-9]{2}|"
    r"gi7eb~[1-9][0-9]|gi7eba~[1-9])[ .]*(?::[\s\S]*)?\Z",
    re.IGNORECASE,
)
_HFS_IGNORED = str.maketrans(
    "",
    "",
    "\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    "\u206a\u206b\u206c\u206d\u206e\u206f\ufeff",
)


def _trusted_tool(path: str) -> str | None:
    try:
        metadata = os.lstat(path)
    except (OSError, UnicodeError, ValueError):
        return None
    safe = (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == 0
        and stat.S_IMODE(metadata.st_mode) & 0o022 == 0
        and os.access(path, os.X_OK)
    )
    return path if safe else None


def _environment() -> dict[str, str]:
    return {
        "HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    git = _trusted_tool(GIT)
    if git is None:
        return None
    try:
        return subprocess.run(
            [git, "--no-replace-objects", "-C", str(root), *args],
            capture_output=True,
            check=False,
            env=_environment(),
        )
    except (OSError, UnicodeError, ValueError):
        return None


def _package_tree(root: Path) -> bool:
    """Treat either generated root marker as a package, without trusting its contents."""
    for name in (PACKAGE_RECEIPT, DISTRIBUTION_MANIFEST):
        try:
            (root / name).lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        return True
    return False


def _trusted_source_root(root: Path) -> bool:
    top = _run(root, "rev-parse", "--show-toplevel")
    remote = _run(root, "remote", "get-url", "origin")
    package_markers = _run(
        root,
        "ls-tree",
        "--name-only",
        "HEAD",
        "--",
        PACKAGE_RECEIPT,
        DISTRIBUTION_MANIFEST,
    )
    return not (
        top is None
        or top.returncode != 0
        or remote is None
        or remote.returncode != 0
        or remote.stdout.strip() not in CANONICAL_REMOTES
        or package_markers is None
        or package_markers.returncode != 0
        or bool(package_markers.stdout)
        or not marker_matches(root)
        or not _tracked(root, [SOURCE_ROOT_MARKER])
    )


def _signed_context(root: Path) -> bool:
    ssh_keygen = _trusted_tool(SSH_KEYGEN)
    if ssh_keygen is None or not _trusted_source_root(root):
        return False
    top = _run(root, "rev-parse", "--show-toplevel")
    assert top is not None
    try:
        if Path(top.stdout.decode("utf-8").strip()).resolve() != root.resolve():
            return False
        with tempfile.TemporaryDirectory(prefix="korpus-trusted-git-") as temporary:
            allowed = Path(temporary) / "allowed-signers"
            allowed.write_bytes(TRUSTED_SIGNERS)
            verified = _run(
                root,
                "-c",
                "gpg.format=ssh",
                "-c",
                f"gpg.ssh.allowedSignersFile={allowed}",
                "-c",
                f"gpg.ssh.program={ssh_keygen}",
                "verify-commit",
                "--raw",
                "HEAD",
            )
    except (OSError, UnicodeError):
        return False
    return verified is not None and verified.returncode == 0


def _canonical_relative(relative: str) -> bool:
    try:
        relative.encode("utf-8", "strict")
    except UnicodeError:
        return False
    path = PurePosixPath(relative)
    parts = path.parts
    dotgit = any(_dotgit_component(part) for part in parts)
    gitmodules = bool(parts) and _gitmodules_component(parts[-1])
    return (
        bool(relative)
        and "\x00" not in relative
        and "\\" not in relative
        and not path.is_absolute()
        and path.as_posix() == relative
        and ".." not in path.parts
        and not dotgit
        and not gitmodules
    )


def _dotgit_component(part: str) -> bool:
    return (
        _NTFS_DOTGIT.fullmatch(part) is not None
        or part.translate(_HFS_IGNORED).casefold() == ".git"
    )


def _gitmodules_component(part: str) -> bool:
    return (
        _NTFS_GITMODULES.fullmatch(part) is not None
        or part.translate(_HFS_IGNORED).casefold() == ".gitmodules"
    )


def _head_records(root: Path, relatives: list[str]) -> dict[str, tuple[str, str]] | None:
    listing = _run(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD", "--", *relatives)
    if listing is None or listing.returncode != 0:
        return None
    records: dict[str, tuple[str, str]] = {}
    try:
        for raw in listing.stdout.split(b"\0"):
            if not raw:
                continue
            metadata, separator, name = raw.partition(b"\t")
            mode, kind, object_id = metadata.decode("ascii").split()
            relative = name.decode("utf-8")
            if not separator or kind != "blob" or mode not in {"100644", "100755"}:
                return None
            records[relative] = (mode, object_id)
    except (UnicodeError, ValueError):
        return None
    return records if set(records) == set(relatives) else None


def _tracked(root: Path, relatives: list[str]) -> bool:
    if not all(_canonical_relative(relative) for relative in relatives):
        return False
    try:
        modes = {relative: (root / relative).lstat().st_mode for relative in relatives}
    except OSError:
        return False
    records = _head_records(root, relatives)
    if records is None:
        return False
    try:
        for relative, filesystem_mode in modes.items():
            tree_mode, object_id = records[relative]
            blob = _run(root, "cat-file", "blob", object_id)
            if (
                not stat.S_ISREG(filesystem_mode)
                or stat.S_IMODE(filesystem_mode) & 0o7000
                or (tree_mode == "100755") != bool(filesystem_mode & 0o111)
                or blob is None
                or blob.returncode != 0
                or blob.stdout != (root / relative).read_bytes()
            ):
                return False
    except OSError:
        return False
    return True


def canonical_paths_admitted(root: Path, relatives: list[str]) -> bool:
    """Admit exact signed-HEAD bytes only in the canonical trusted Git context."""
    if not relatives or len(relatives) != len(set(relatives)):
        return False
    if _package_tree(root) or not _signed_context(root):
        return False
    return _tracked(root, relatives)
