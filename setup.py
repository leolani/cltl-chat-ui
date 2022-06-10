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
        # setuptools doesn't expand /**/* globs (https://github.com/pypa/setuptools/issues/1806)
        "cltl_service.chatui": ["static/*", "static/*/*", "static/*/*/*", "static/*/*/*/*", "static/*/*/*/*/*"]
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
        ]}
)
