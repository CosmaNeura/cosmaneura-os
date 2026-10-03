"""Standalone private PDF inspector. Only a bounded page count is emitted."""

import importlib
import io
import sys


def main():
    try:
        # The deployment must support process resource fencing. Unsupported
        # platforms remain unavailable rather than silently parsing in-process.
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        # Darwin rejects lowering RLIMIT_AS/DATA for this runtime. Its parent
        # monitors resident memory and kills the inspector at the same bound.
        if sys.platform != "darwin":
            _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            bounded_memory = 268435456 if hard == resource.RLIM_INFINITY else min(hard, 268435456)
            resource.setrlimit(resource.RLIMIT_AS, (bounded_memory, bounded_memory))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        PdfReader = importlib.import_module("pypdf").PdfReader
        document = sys.stdin.buffer.read(1048577)
        if (
            not 1 <= len(document) <= 1048576
            or not document.startswith(b"%PDF-")
            or not document.rstrip().endswith(b"%%EOF")
            or b"/Encrypt" in document
        ):
            raise ValueError
        reader = PdfReader(io.BytesIO(document), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 50:
            raise ValueError
        unsafe = {
            "/JS",
            "/JavaScript",
            "/OpenAction",
            "/AA",
            "/Launch",
            "/EmbeddedFiles",
            "/Filespec",
            "/AcroForm",
            "/XFA",
            "/URI",
            "/SubmitForm",
            "/RichMedia",
            "/GoToR",
        }
        seen = set()

        def walk(value, depth=0):
            if depth > 24 or len(seen) > 8192:
                raise ValueError
            if hasattr(value, "get_object"):
                value = value.get_object()
            if id(value) in seen:
                return
            seen.add(id(value))
            if isinstance(value, dict):
                if unsafe & {str(key) for key in value}:
                    raise ValueError
                for item in value.values():
                    walk(item, depth + 1)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item, depth + 1)

        walk(reader.trailer)
        sys.stdout.write(str(len(reader.pages)))
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
