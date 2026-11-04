"""Read one file from Valve VPK archives using the VPK 1/2 directory format."""
import hashlib
import struct
from pathlib import Path

MAGIC = 0x55AA1234


def read_file(vpk_path: Path, wanted: str) -> bytes:
    vpk_path = Path(vpk_path)
    data = vpk_path.read_bytes()
    magic, version, tree_size = struct.unpack_from('<III', data)
    if magic != MAGIC or version not in (1, 2):
        raise ValueError('Unsupported VPK archive')
    header_size = 28 if version == 2 else 12
    position = header_size
    end_of_tree = header_size + tree_size

    def read_string():
        nonlocal position
        end = data.index(0, position, end_of_tree)
        value = data[position:end].decode('utf-8')
        position = end + 1
        return value

    while extension := read_string():
        while directory := read_string():
            while name := read_string():
                _, preload_size, archive, offset, length, terminator = struct.unpack_from('<IHHIIH', data, position)
                position += 18
                if terminator != 0xFFFF:
                    raise ValueError('Corrupt VPK entry')
                preload = data[position:position + preload_size]
                position += preload_size
                filename = f'{directory}/{name}.{extension}'
                if filename != wanted:
                    continue
                archive_path = (vpk_path if archive == 0x7FFF else
                                vpk_path.with_name(f'{vpk_path.stem.removesuffix("_dir")}_{archive:03d}.vpk'))
                start = offset + (end_of_tree if archive == 0x7FFF else 0)
                with archive_path.open('rb') as archive_file:
                    archive_file.seek(start)
                    payload = archive_file.read(length)
                if len(payload) != length:
                    raise ValueError('Truncated VPK entry')
                return preload + payload
    raise FileNotFoundError(wanted)


def source_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
