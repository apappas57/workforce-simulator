import io
import zipfile
from typing import Dict


def to_csv_bytes(df) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def build_zip_bytes(files: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()