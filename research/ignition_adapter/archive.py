"""Pure in-memory editing of an existing View; never extracts an archive."""
import io
import json
from pathlib import PurePosixPath
import zipfile
from .core import AdapterError, MAX_BYTES


def checked_archive(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise AdapterError('invalid_project_archive')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            seen, total = set(), 0
            for info in archive.infolist():
                name = info.filename
                total += info.file_size
                if (name in seen or '\\' in name or name.startswith('/') or
                        '..' in PurePosixPath(name).parts or total > MAX_BYTES):
                    raise AdapterError('invalid_project_archive')
                seen.add(name)
            if 'project.json' not in seen:
                raise AdapterError('invalid_project_archive')
            for info in archive.infolist():
                archive.read(info)  # Validate CRC/decompression while bounded by declared sizes.
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
        raise AdapterError('invalid_project_archive') from None
    return data


def patch_existing_view(archive, resource_path, view):
    """Replace only an existing View JSON, retaining unknown files and ZIP metadata.

    This is neither a component semantic validator nor an atomic server update.
    """
    checked_archive(archive)
    if (not isinstance(resource_path, str) or
            not resource_path.startswith('com.inductiveautomation.perspective/views/') or
            not resource_path.endswith('/view.json') or not isinstance(view, dict)):
        raise AdapterError('existing_view_required')
    output = io.BytesIO()
    try:
        replacement = json.dumps(view, ensure_ascii=False, allow_nan=False).encode()
        with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(output, 'w') as target:
            if resource_path not in source.namelist():
                raise AdapterError('existing_view_required')
            target.comment = source.comment
            for info in source.infolist():
                target.writestr(info, replacement if info.filename == resource_path else source.read(info))
    except (ValueError, TypeError):
        raise AdapterError('invalid_view_json') from None
    return checked_archive(output.getvalue())
