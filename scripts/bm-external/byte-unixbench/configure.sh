#!/bin/sh
# Copyright (C) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# SPDX-License-Identifier: MIT

set -ex
SRC_DIR="$(readlink -f $(dirname "$0")/../../..)"
BUILD_DIR=${SRC_DIR}/bm-external

echo $BUILD_DIR

TAG=v6.0.1

mkdir -p ${BUILD_DIR}
(
	cd ${BUILD_DIR}
	if [ ! -e byte-unixbench/.git ]; then
		git clone https://github.com/kdlucas/byte-unixbench --branch ${TAG}
	else
	    (cd byte-unixbench/UnixBench && make clean|| true)
	fi
	cd byte-unixbench/UnixBench
	make
)
