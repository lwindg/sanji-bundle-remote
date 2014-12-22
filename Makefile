all: pylint test

pylint:
	flake8 --exclude=.git,__init__.py -v .
test:
	nosetests --with-coverage --cover-erase --cover-package=agent -v
tox:
	tox

.PHONY: pylint test tox
