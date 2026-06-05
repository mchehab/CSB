#!/bin/sh
# Copyright (C) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# SPDX-License-Identifier: MIT

set -ex
SCRIPT_DIR="$(readlink -f $(dirname "$0")/../../../bm-external)"

echo $SCRIPT_DIR

TAG=v6.0.1

mkdir -p ${SCRIPT_DIR}
(
	cd ${SCRIPT_DIR}
	if [ ! -e byte-unixbench/.git ]; then
		git clone https://github.com/kdlucas/byte-unixbench --branch ${TAG}
	else
	    (cd byte-unixbench/UnixBench && make clean|| true)
	fi
	cd byte-unixbench/UnixBench
	make
)
