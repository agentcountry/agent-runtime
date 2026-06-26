from setuptools import setup, find_packages

setup(
    name="agent-runtime",
    version="0.1.0",
    description="24/7 background runtime for AI agents — ARMP + Matrix powered",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Agent Country",
    url="https://github.com/agentcountry/agent-runtime",
    license="Apache 2.0",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "matrix-nio>=0.24",
        "aiofiles>=23.0",
    ],
    extras_require={
        "arrup": ["amp_sdk"],  # ARMP SDK (from armp-protocol repo)
    },
    classifiers=[
        "Development Status :: 3 — Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Topic :: Communications :: Chat",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
