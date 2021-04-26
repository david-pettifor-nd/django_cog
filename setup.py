import pathlib
from setuptools import setup

# The directory containing this file
HERE = pathlib.Path(__file__).parent

# The text of the README file
README = (HERE / "README.md").read_text()

# This call to setup() does all the work
setup(
    name="django-cog",
    version="0.1.2",
    description="Django library for launching pipelines of multiple stages and parallel tasks.",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/david-pettifor-nd/django_cog.git",
    author="David W Pettifor",
    author_email="dpettifo@nd.edu",
    license="GPL",
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Framework :: Django :: 2.2"
    ],
    packages=["django_cog"],
    include_package_data=True,
    install_requires=["celery", "django-celery-beat"]
)
