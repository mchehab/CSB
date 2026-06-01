#!/bin/bash -e
# Copyright (C) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# SPDX-License-Identifier: MIT

SCRIPT_DIR="$(readlink -f $(dirname "$0")/../..)"

cd $SCRIPT_DIR/bm-external/sysbench/share/sysbench/
exec $SCRIPT_DIR/bm-external/sysbench/bin/sysbench "$@"
