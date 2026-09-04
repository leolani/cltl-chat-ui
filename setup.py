from setuptools import setup, find_namespace_packages

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
        # The front end is vendored, so everything under static/ has to ship:
        # chat-bubble, Annotorious, and the page's own HTML/CSS/JS. The explicit
        # depth ladder is a workaround for package_data not supporting **.
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
    # `requests` is for the best-effort PUT of uploaded pixels to cltl-backend's
    # image storage. cv2 is deliberately NOT declared: two differently named
    # distributions provide it (opencv-python in the app and harness virtual
    # environments, opencv-python-headless in cltl-base-slim), and naming either
    # breaks the other environment's --no-index install. See
    # ChatUiService._decode_rgb.
    install_requires=['emissor', 'cltl.combot', 'requests'],
    extras_require={
        "impl": [],
        "service": [
            "emissor",
            "flask"
        ]
    },
)
