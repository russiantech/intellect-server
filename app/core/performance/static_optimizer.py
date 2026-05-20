# """
# app/core/performance/static_optimizer.py — Production static file optimization.
# Generates hashed filenames, compresses assets, sets long cache headers.
# """

# import os
# import hashlib
# import gzip
# import shutil
# from pathlib import Path
# from typing import Dict, List

# class StaticOptimizer:
#     """Optimize static files for CDN/caching."""

#     def __init__(self, static_dir: str = "static", output_dir: str = "static/dist"):
#         self.static_dir = Path(static_dir)
#         self.output_dir = Path(output_dir)
#         self.manifest: Dict[str, str] = {}  # original -> hashed

#     def generate_hash(self, filepath: Path) -> str:
#         """Generate content hash for cache busting."""
#         hasher = hashlib.md5()
#         with open(filepath, "rb") as f:
#             for chunk in iter(lambda: f.read(8192), b""):
#                 hasher.update(chunk)
#         return hasher.hexdigest()[:8]

#     def compress_file(self, src: Path, dst: Path):
#         """Create .gz version for nginx/cPanel gzip_static."""
#         with open(src, "rb") as f_in:
#             with gzip.open(str(dst) + ".gz", "wb", compresslevel=9) as f_out:
#                 shutil.copyfileobj(f_in, f_out)

#     def optimize(self, extensions: List[str] = None):
#         """Process all static files."""
#         extensions = extensions or [".css", ".js", ".svg", ".png", ".jpg", ".jpeg"]

#         # Clean output
#         if self.output_dir.exists():
#             shutil.rmtree(self.output_dir)
#         self.output_dir.mkdir(parents=True, exist_ok=True)

#         for ext in extensions:
#             for filepath in self.static_dir.rglob(f"*{ext}"):
#                 if filepath.is_dir():
#                     continue

#                 # Generate hashed filename: app.js -> app.a1b2c3d4.js
#                 file_hash = self.generate_hash(filepath)
#                 stem = filepath.stem
#                 suffix = filepath.suffix
#                 hashed_name = f"{stem}.{file_hash}{suffix}"

#                 # Copy to output with hash
#                 relative = filepath.relative_to(self.static_dir)
#                 output_path = self.output_dir / relative.parent / hashed_name
#                 output_path.parent.mkdir(parents=True, exist_ok=True)
#                 shutil.copy2(filepath, output_path)

#                 # Compress
#                 self.compress_file(filepath, output_path)

#                 # Store manifest entry
#                 original_key = str(relative).replace("\", "/")
#                 hashed_key = str(relative.parent / hashed_name).replace("\", "/")
#                 self.manifest[original_key] = hashed_key

#         # Write manifest.json for template rendering
#         manifest_path = self.output_dir / "manifest.json"
#         import json
#         with open(manifest_path, "w") as f:
#             json.dump(self.manifest, f, indent=2)

#         print(f"✅ Optimized {len(self.manifest)} files to {self.output_dir}")
#         return self.manifest

#     def get_url(self, original_path: str) -> str:
#         """Get hashed URL for template rendering."""
#         return self.manifest.get(original_path, original_path)

# # CLI usage
# if __name__ == "__main__":
#     import sys
#     static_dir = sys.argv[1] if len(sys.argv) > 1 else "static"
#     output_dir = sys.argv[2] if len(sys.argv) > 2 else "static/dist"

#     opt = StaticOptimizer(static_dir, output_dir)
#     opt.optimize()



# v2
# app/core/performance/static_optimizer.py
#
# Build-time static asset optimizer for Intellect LMS.
#
# What it does:
#   1. Copies each matching file to static/dist/ with a content-hash suffix
#      for long-lived browser caching (e.g. app.js → app.a1b2c3d4.js).
#   2. Creates a .gz sidecar for every output file so nginx/cPanel can serve
#      pre-compressed assets via gzip_static without on-the-fly compression.
#   3. Writes static/dist/manifest.json mapping original → hashed paths,
#      which your Jinja2 / template layer can read to inject correct URLs.
#
# Run as a build step (e.g. in your deploy script):
#
#   python -m app.core.static_optimizer
#   python -m app.core.static_optimizer static static/dist
#
# Or call programmatically:
#
#   from app.core.performance.static_optimizer import StaticOptimizer
#   manifest = StaticOptimizer().optimize()

import gzip
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class StaticOptimizer:
    """
    Content-hash static file optimizer.

    Args:
        static_dir:  Source directory containing raw static assets.
        output_dir:  Destination directory for hashed + compressed output.
    """

    DEFAULT_EXTENSIONS = [".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp"]

    def __init__(
        self,
        static_dir: str = "static",
        output_dir: str = "static/dist",
    ):
        self.static_dir = Path(static_dir)
        self.output_dir = Path(output_dir)
        self.manifest: Dict[str, str] = {}

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _content_hash(filepath: Path) -> str:
        """Return an 8-character MD5 hash of the file's contents."""
        hasher = hashlib.md5()
        with open(filepath, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()[:8]

    @staticmethod
    def _write_gzip_sidecar(src: Path, dst: Path):
        """
        Write a .gz sidecar next to `dst` so nginx gzip_static can serve it.
        The sidecar path is dst.with_suffix(dst.suffix + '.gz').
        """
        gz_path = Path(str(dst) + ".gz")
        with open(src, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)

    # ── Public API ────────────────────────────────────────────────

    def optimize(
        self,
        extensions: Optional[List[str]] = None,
        clean: bool = True,
    ) -> Dict[str, str]:
        """
        Process all static files in `static_dir` and write hashed copies
        (plus .gz sidecars) to `output_dir`.

        Args:
            extensions: File extensions to process. Defaults to DEFAULT_EXTENSIONS.
            clean:      If True, wipe `output_dir` before rebuilding. Default True.

        Returns:
            Manifest dict: {original_relative_path: hashed_relative_path}
        """
        if not self.static_dir.exists():
            raise FileNotFoundError(f"Static source directory not found: {self.static_dir}")

        extensions = extensions or self.DEFAULT_EXTENSIONS
        self.manifest = {}

        if clean and self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        processed = 0
        for ext in extensions:
            for src in self.static_dir.rglob(f"*{ext}"):
                if not src.is_file():
                    continue

                file_hash = self._content_hash(src)
                hashed_name = f"{src.stem}.{file_hash}{src.suffix}"

                relative = src.relative_to(self.static_dir)
                dst = self.output_dir / relative.parent / hashed_name
                dst.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(src, dst)
                self._write_gzip_sidecar(src, dst)

                # Normalise to forward slashes for cross-platform manifest keys
                original_key = relative.as_posix()
                hashed_key = (relative.parent / hashed_name).as_posix()
                self.manifest[original_key] = hashed_key
                processed += 1

        manifest_path = self.output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(self.manifest, fh, indent=2, sort_keys=True)

        logger.info(
            "Static optimizer: %d file(s) written to '%s'.",
            processed,
            self.output_dir,
        )
        return self.manifest

    def get_url(self, original_path: str, prefix: str = "/static/dist") -> str:
        """
        Resolve a source-relative path to its hashed CDN/static URL.

        Args:
            original_path: e.g. "css/main.css"
            prefix:        URL prefix served by your web server. Default "/static/dist".

        Returns:
            Hashed URL e.g. "/static/dist/css/main.a1b2c3d4.css",
            or the original prefixed path if no manifest entry exists.
        """
        hashed = self.manifest.get(original_path, original_path)
        return f"{prefix.rstrip('/')}/{hashed.lstrip('/')}"

    @classmethod
    def load_manifest(
        cls,
        manifest_path: str = "static/dist/manifest.json",
    ) -> Dict[str, str]:
        """
        Load a previously generated manifest from disk.
        Use this at app startup to resolve hashed URLs in templates.

        Usage:
            MANIFEST = StaticOptimizer.load_manifest()

            @app.context_processor
            def inject_static():
                return {"static_url": lambda p: MANIFEST.get(p, p)}
        """
        path = Path(manifest_path)
        if not path.exists():
            logger.warning("Static manifest not found at '%s'. Run the optimizer first.", path)
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)


# ── CLI entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    static_dir = sys.argv[1] if len(sys.argv) > 1 else "static"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "static/dist"

    optimizer = StaticOptimizer(static_dir, output_dir)
    manifest = optimizer.optimize()
    print(f"Manifest written with {len(manifest)} entries.")

