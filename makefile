SHELL = /bin/bash


project_dependencies ?= $(addprefix $(project_root)/, emissor cltl-combot)

git_remote ?= https://github.com/leolani


include util/make/makefile.base.mk
include util/make/makefile.py.base.mk
include util/make/makefile.git.mk
include util/make/makefile.component.mk


clean: py-clean
	rm -rf src/cltl_service/chatui/static/chat-bubble
