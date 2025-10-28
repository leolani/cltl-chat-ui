from setuptools import setup, find_namespace_packages
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist
try:
    # Optional: only present if 'wheel' is installed when you build a wheel
    from wheel.bdist_wheel import bdist_wheel as _bdist_wheel
except Exception:  # pragma: no cover
    _bdist_wheel = None

import os
import tarfile
import tempfile
import urllib.request
import pathlib
import shutil


# --------- chat-bubble fetch ---------
ROOT = pathlib.Path(__file__).parent.resolve()

CHAT_BUBBLE_VERSION = "1.5.0"
CHAT_BUBBLE_URL = f"https://github.com/dmitrizzle/chat-bubble/archive/refs/tags/v{CHAT_BUBBLE_VERSION}.tar.gz"

# Where to place the extracted assets
TARGET_DIR = ROOT / "src" / "cltl_service" / "chatui" / "static" / "chat-bubble" / "component"
# Subtree inside the tar (strip this prefix)
TAR_PREFIX = f"chat-bubble-{CHAT_BUBBLE_VERSION}/component"

def _safe_join(base: pathlib.Path, *paths: str) -> pathlib.Path:
    """Prevent path traversal outside base."""
    dest = (base / pathlib.Path(*paths)).resolve()
    base = base.resolve()
    if not str(dest).startswith(str(base) + os.sep) and dest != base:
        raise RuntimeError(f"Blocked unsafe path: {dest}")
    return dest

def _extract_subdir_from_tar(tar: tarfile.TarFile, subdir_prefix: str, out_dir: pathlib.Path) -> None:
    """Extract only files under subdir_prefix/ into out_dir, stripping the prefix."""
    for member in tar.getmembers():
        name = member.name
        if not name.startswith(subdir_prefix + "/") and name != subdir_prefix:
            continue

        rel = name[len(subdir_prefix):].lstrip("/")
        if not rel:
            continue  # directory root

        dest = _safe_join(out_dir, rel)

        if member.isdir():
            dest.mkdir(parents=True, exist_ok=True)
        elif member.issym() or member.islnk():
            # Skip symlinks for safety; add handling if needed
            continue
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, open(dest, "wb") as dst:
                if src is None:
                    continue
                shutil.copyfileobj(src, dst)

def fetch_chat_bubble(force: bool = True) -> None:
    """Download and unpack chat-bubble's component/ into TARGET_DIR."""
    if TARGET_DIR.exists() and not force:
        return

    # Clean target (like `make clean`)
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # Download tarball
    with tempfile.TemporaryDirectory() as td:
        tmp_path = pathlib.Path(td) / f"chat-bubble-v{CHAT_BUBBLE_VERSION}.tar.gz"
        print(f"Downloading {CHAT_BUBBLE_URL} ...")
        with urllib.request.urlopen(CHAT_BUBBLE_URL) as resp:
            data = resp.read()
        with open(tmp_path, "wb") as f:
            f.write(data)

        # Extract only the component/ subtree
        print(f"Extracting {TAR_PREFIX}/ -> {TARGET_DIR}")
        with tarfile.open(tmp_path, "r:gz") as tar:
            _extract_subdir_from_tar(tar, TAR_PREFIX, TARGET_DIR)

    # Sanity check
    if not any(TARGET_DIR.iterdir()):
        raise RuntimeError(
            "chat-bubble extraction produced no files; check version or upstream layout."
        )

class build_py(_build_py):
    def run(self):
        fetch_chat_bubble(force=True)
        super().run()

class sdist(_sdist):
    def run(self):
        fetch_chat_bubble(force=True)
        super().run()

cmdclass = {"build_py": build_py, "sdist": sdist}

if _bdist_wheel is not None:
    class bdist_wheel(_bdist_wheel):
        def run(self):
            fetch_chat_bubble(force=True)
            super().run()
    cmdclass["bdist_wheel"] = bdist_wheel

# --------- END: chat-bubble fetch ---------


with open("README.md", "r") as fh:
    long_description = fh.read()

with open("VERSION", "r") as fh:
    version = fh.read().strip()

setup(
    name='cltl.chat-ui',
    version=version,
    package_dir={'': 'src'},
    packages=find_namespace_packages(include=['cltl.*', 'cltl_service.*'], where='src'),
    package_data={
        # include nested static files; your glob workaround stays
        "cltl_service.chatui": [
            "static/*", "static/*/*", "static/*/*/*", "static/*/*/*/*", "static/*/*/*/*/*"
        ]
    },
    data_files=[('VERSION', ['VERSION'])],
    url="https://github.com/leolani/cltl-chat-ui",
    license='MIT License',
    author='CLTL',
    author_email='t.baier@vu.nl',
    description='Simple chat user interface',
    long_description=long_description,
    long_description_content_type="text/markdown",
    python_requires='>=3.8',
    install_requires=['emissor', 'cltl.combot'],
    extras_require={
        "impl": [],
        "service": [
            "emissor",
            "flask"
        ]
    },
    cmdclass=cmdclass,  # <-- wire in the build hooks
)
