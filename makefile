SHELL = /bin/bash


project_dependencies ?= $(addprefix $(project_root)/, emissor cltl-combot)

git_remote ?= https://github.com/leolani


include util/make/makefile.base.mk
include util/make/makefile.py.base.mk
include util/make/makefile.git.mk
include util/make/makefile.component.mk
include util/make/makefile.docker.mk


# The front end is vendored under src/cltl_service/chatui/static/, so there is
# nothing to fetch and nothing to clean beyond the Python build artefacts.
clean: py-clean
