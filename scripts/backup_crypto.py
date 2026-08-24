#!/usr/bin/env python3
"""Streaming AES-256-GCM encryption for PostgreSQL backup artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"KORPUS-BACKUP\x01"
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_BYTES = 1024 * 1024


def load_key(path: Path) -> bytes:
    raw = path.read_text(encoding="ascii").strip()
    if len(raw) != 64:
        raise SystemExit("backup encryption key must be exactly 64 hexadecimal characters")
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise SystemExit("backup encryption key is not valid hexadecimal") from exc
    if len(key) != 32:
        raise SystemExit("backup encryption key must decode to 32 bytes")
    return key


def fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _encrypt_reader(reader: BinaryIO, destination: Path, key: bytes) -> tuple[str, int]:
    nonce = os.urandom(NONCE_BYTES)
    header = MAGIC + nonce
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    plaintext_hash = hashlib.sha256()
    plaintext_bytes = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as writer:
            writer.write(header)
            while chunk := reader.read(CHUNK_BYTES):
                plaintext_hash.update(chunk)
                plaintext_bytes += len(chunk)
                writer.write(encryptor.update(chunk))
            writer.write(encryptor.finalize())
            writer.write(encryptor.tag)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(destination, 0o600)
        fsync_parent(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return plaintext_hash.hexdigest(), plaintext_bytes


def encrypt(source: Path, destination: Path, key: bytes) -> tuple[str, int]:
    with source.open("rb") as reader:
        return _encrypt_reader(reader, destination, key)


def encrypt_stream(reader: BinaryIO, destination: Path, key: bytes) -> tuple[str, int]:
    return _encrypt_reader(reader, destination, key)


def decrypt(source: Path, destination: Path, key: bytes) -> tuple[str, int]:
    size = source.stat().st_size
    header_size = len(MAGIC) + NONCE_BYTES
    if size <= header_size + TAG_BYTES:
        raise SystemExit("encrypted backup is truncated")
    plaintext_hash = hashlib.sha256()
    plaintext_bytes = 0
    with source.open("rb") as reader:
        header = reader.read(header_size)
        if not header.startswith(MAGIC):
            raise SystemExit("encrypted backup magic/version mismatch")
        nonce = header[len(MAGIC) :]
        reader.seek(-TAG_BYTES, os.SEEK_END)
        tag = reader.read(TAG_BYTES)
        ciphertext_bytes = size - header_size - TAG_BYTES
        reader.seek(header_size)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as writer:
                remaining = ciphertext_bytes
                while remaining:
                    chunk = reader.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise SystemExit("encrypted backup ended unexpectedly")
                    remaining -= len(chunk)
                    plaintext = decryptor.update(chunk)
                    plaintext_hash.update(plaintext)
                    plaintext_bytes += len(plaintext)
                    writer.write(plaintext)
                final = decryptor.finalize()
                plaintext_hash.update(final)
                plaintext_bytes += len(final)
                writer.write(final)
                writer.flush()
                os.fsync(writer.fileno())
            os.chmod(destination, 0o600)
            fsync_parent(destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    return plaintext_hash.hexdigest(), plaintext_bytes


def _write_metadata(path: Path, sha256: str, size: int) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump({"sha256": sha256, "bytes": size}, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)
    fsync_parent(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("encrypt", "encrypt-stdin", "decrypt"))
    parser.add_argument("source")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--metadata-file", type=Path)
    args = parser.parse_args()
    key = load_key(args.key_file)
    if args.destination.exists():
        raise SystemExit("destination already exists")
    if args.metadata_file is not None and args.metadata_file.exists():
        raise SystemExit("metadata destination already exists")
    if args.mode == "encrypt-stdin":
        if args.source != "-" or args.metadata_file is None:
            raise SystemExit("encrypt-stdin requires source '-' and --metadata-file")
        sha256, size = encrypt_stream(sys.stdin.buffer, args.destination, key)
        _write_metadata(args.metadata_file, sha256, size)
    elif args.mode == "encrypt":
        sha256, size = encrypt(Path(args.source), args.destination, key)
        if args.metadata_file is not None:
            _write_metadata(args.metadata_file, sha256, size)
    else:
        sha256, size = decrypt(Path(args.source), args.destination, key)
        if args.metadata_file is not None:
            _write_metadata(args.metadata_file, sha256, size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
