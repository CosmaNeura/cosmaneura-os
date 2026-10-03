"""Bounded separate-process inspection of an untrusted received PDF.

No document text, credentials or user identifiers reach diagnostics. pypdf is
an optional pinned inbound dependency; absence fails closed without rendering.
"""

import asyncio
import os
import sys
from pathlib import Path

from cosmas_os.ports.efax_inbound import MAX_PAGES, MAX_PDF_BYTES, Failure


async def _monitor_memory(process: asyncio.subprocess.Process) -> None:
    """Darwin RSS watchdog; addresses only this inspector's numeric PID."""
    while process.returncode is None:
        probe = None
        try:
            probe = await asyncio.create_subprocess_exec(
                "/bin/ps",
                "-o",
                "rss=",
                "-p",
                str(process.pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={"PATH": os.defpath},
                close_fds=True,
            )
            async with asyncio.timeout(0.5):
                output, _ = await probe.communicate()
            if process.returncode is not None:
                return
            if (
                probe.returncode != 0
                or len(output) > 32
                or not output.strip().isdigit()
                or int(output) > 262144
            ):
                process.kill()
                raise Failure("document_needs_human")
        finally:
            if probe is not None and probe.returncode is None:
                probe.kill()
                await asyncio.shield(probe.wait())
        await asyncio.sleep(0.05)


async def validate_received_pdf(document: bytes) -> int:
    if (
        type(document) is not bytes
        or not 1 <= len(document) <= MAX_PDF_BYTES
        or not document.startswith(b"%PDF-")
        or not document.rstrip().endswith(b"%%EOF")
    ):
        raise Failure("document_needs_human")
    worker = Path(__file__).with_name("_efax_pdf_worker.py")
    process = None
    monitor = None
    try:
        async with asyncio.timeout(5):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-B",
                str(worker),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={"PATH": os.defpath},
                close_fds=True,
            )
            if sys.platform == "darwin":
                monitor = asyncio.create_task(_monitor_memory(process))
            output, _ = await process.communicate(document)
            if monitor is not None:
                await monitor
        if (
            process.returncode != 0
            or len(output) > 16
            or not output.isascii()
            or not output.strip().isdigit()
            or not 1 <= int(output) <= MAX_PAGES
        ):
            raise Failure("document_needs_human")
        return int(output)
    except (OSError, TimeoutError):
        raise Failure("document_needs_human") from None
    finally:
        if monitor is not None and not monitor.done():
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
        if process is not None and process.returncode is None:
            process.kill()
            await asyncio.shield(process.wait())
