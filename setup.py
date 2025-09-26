from setuptools import setup, find_packages

setup(
    name="crypto-signal-bot",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "python-telegram-bot==20.7",
        "ccxt==4.1.72",
        "pandas==2.0.3",
        "numpy==1.24.3",
        "schedule==1.2.0",
        "python-dotenv==1.0.0",
        "requests==2.31.0",
    ],
    python_requires=">=3.8",
)
