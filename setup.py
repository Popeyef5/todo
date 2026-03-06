from setuptools import setup, find_packages

setup(
    name="todo",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[],
    entry_points={
        'console_scripts': [
            'todo=todo.cli:main',
        ],
    },
    author="Todo Contributors",
    description="Git-like TODO management with multi-device sync",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/user/todo",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8+",
    ],
    python_requires=">=3.8",
)