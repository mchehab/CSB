#!/bin/sh
# Copyright (C) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# SPDX-License-Identifier: MIT

set -e
SCRIPT_DIR="$(readlink -f $(dirname "$0")/..)"

${SCRIPT_DIR}/deps/benchkit/scripts/install_venv.sh

(
	cd ${SCRIPT_DIR}/deps/sysbench/
	./autogen.sh
	./configure --with-mysql --with-pgsql --prefix=${SCRIPT_DIR}/build/sysbench
	make
	make install
)
