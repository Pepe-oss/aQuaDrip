from setuptools import setup, find_packages

setup(
    name="wdrip-core",
    version="0.1.0.dev",
    description="基于 WNTR 的智能滴灌管网核心库",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="aQuaDrip",
    license="GPL v3",
    packages=find_packages(where="."),
    package_dir={"": "."},
    python_requires=">=3.9",
    install_requires=[
        "wntr>=0.3.0",
        "numpy>=1.21",
        "scipy>=1.7",
        "shapely>=2.0",
        "pandas>=1.3",
        "geopandas>=0.12",
        "networkx>=2.8",
        "matplotlib>=3.5",
    ],
    extras_require={
        "dem": ["rasterio>=1.3"],
        "dev": ["pytest", "pytest-cov", "flake8", "black"],
        "docs": ["sphinx"],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3.9",
        "Topic :: Scientific/Engineering :: Hydrology",
    ],
)
