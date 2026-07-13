# Copyright (C) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# SPDX-License-Identifier: MIT

import json
import sys
import logging
from typing import Optional
from json import JSONDecodeError
from pathlib import Path
from config.plugin import Plugin
from config.plot import PlotConfig
from config.container import ContainersConfig
from config.application import Application
from config.benchmark import BenchmarkConfig
import shutil
from config.nics import NicsConfig
from utils.logger import bm_log, LogType
from bm_utils import get_host_ip


def construct_bm_name(fname: str):
    """
    Constructs the benchmark name based on the given
    configuration file name.
    """
    config_file = Path(fname)

    # return parts without ext
    parts = list(config_file.with_suffix("").parts)
    # remove everything before and including config
    if "config" in parts:
        parts = parts[parts.index("config") + 1 :]
        # if external is in the path remove it as well
        if parts and parts[0] == "bm-external":
            parts = parts[1:]
        # now join with `_`
        return "_".join(parts)
    else:
        return config_file.stem


class CampaignConfig:
    CFG_THREADS = "threads"

    def __init__(self, filename: str):
        """
         The overall configuration of a benchmark combines the setups of distinct components, such as application details and networking.
         Only some components need to specified, as displayed below.
         More information on each component is detailed in their own documentations.
         If an object contains duplicate keys, the last one is used.

        Components
         ----------
         bm_cfg: Optional[BenchmarkConfig]
             Benchmark and system-wide configurations.
         apps: list[Application]
             Application-specific configurations.
         container_cfg: Optional[ContainersConfig]
             Container-specific configurations.
         plugins: Optional[list[Plugin]]
             Configuration to run additional scripts through execution.
         plots: Optional[list[PlotConfig]]
             Configuration for plotting results.
         nics: Optional[NicsConfig]
             Network-specific configurations.
        """
        # read JSON file
        self.config_fname = filename
        self.__load(filename)
        self.bm_cfg = self.__parse_benchmark_cfg()
        self.container_cfg = self.__parse_container_cfg()
        self.apps = self.__parse_apps()
        self.plots = self.__parse_plots()
        self.plugins = self.__parse_plugins()
        self.nics = self.__parse_nics()
        self.host_ip = get_host_ip()

    def __load(self, filename: str):
        try:
            with open(filename) as f:
                self.config = json.load(f)
        except FileNotFoundError:
            logging.error(f"Config file: {filename} does not exist!")
            sys.exit(1)
        except JSONDecodeError as e:
            logging.error(f"Invalid JSON in {filename}: {e}")
            sys.exit(1)

    def get(self, key: str):
        """
        Returns the value associated with the given key if it exists.
        """
        return self.config.get(key)

    def get_host_ip(self) -> str:
        # at the moment this is auto-detected
        # we can later allow specifying it in JSON
        return self.host_ip

    def copy(self, des):
        shutil.copy(self.config_fname, des)

    def get_apps(self) -> list[Application]:
        return self.apps

    def __parse_apps(self) -> list[Application]:
        applications = self.config.get(Application.CONFIG_KEY)
        if applications:
            assert isinstance(applications, list), "A list is expected"
            apps = [Application(**app) for app in applications]
            return apps
        else:
            bm_log("Cannot find applications in your json", LogType.FATAL)
            sys.exit(1)

    def __parse_benchmark_cfg(self) -> BenchmarkConfig:
        cfg = self.config.get(BenchmarkConfig.CONFIG_KEY)
        if cfg:
            return BenchmarkConfig(**cfg)
        else:
            return BenchmarkConfig()

    def get_benchmark_cfg(self) -> BenchmarkConfig:
        return self.bm_cfg

    def __parse_plots(self) -> list[PlotConfig]:
        plots = self.config.get(PlotConfig.CONFIG_KEY)
        if plots:
            assert isinstance(plots, list), "A list is expected"
            plot_configs = [PlotConfig(**p) for p in plots]
            return plot_configs
        else:
            return []

    def get_plots(self) -> list[PlotConfig]:
        return self.plots

    def __parse_container_cfg(self) -> ContainersConfig:
        containers = self.config.get(ContainersConfig.CONFIG_KEY)
        if containers:
            return ContainersConfig(**containers)
        else:
            return ContainersConfig()

    def get_container_config(self) -> ContainersConfig:
        return self.container_cfg

    def __parse_plugins(self) -> list[Plugin]:
        plugins = self.config.get(Plugin.CONFIG_KEY)
        if plugins:
            assert isinstance(plugins, list), "A list is expected"
            return [Plugin(**plugin) for plugin in plugins]
        else:
            return []

    def get_plugins(self) -> list[Plugin]:
        return self.plugins

    def __parse_nics(self) -> Optional[NicsConfig]:
        nics = self.config.get(NicsConfig.CONFIG_KEY)
        if nics:
            return NicsConfig(**nics)
        else:
            return None

    def get_nics(self) -> Optional[NicsConfig]:
        return self.nics


# global configuration
g_config: Optional[CampaignConfig] = None
