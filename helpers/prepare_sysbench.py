#!/usr/bin/env python3
# Copyright (C) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# SPDX-License-Identifier: MIT

"""
MariaDB + Sysbench Setup Script
"""

import argparse
import configparser
import os
import re
import subprocess
import sys

from time import sleep
from shutil import which

# === Configuration Defaults ===
DEFAULT_DB_NAME = "sbtest"
DEFAULT_DB_USER = "sbtest"
DEFAULT_DB_PASS = "Password@123"
DEFAULT_PORT = 3306
DEFAULT_CONFIG_FILE = "/etc/my.cnf.d/sysbench.cnf"
DEFAULT_THREADS = 1000
DEFAULT_TABLES = 3
DEFAULT_TABLE_SIZE = 10000
DEFAULT_BENCH_TIME = 1
DEFAULT_MYSQL_CMD = "mariadb"

DEFAULT_SYSBENCH_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bm-external", "sysbench"
)
DEFAULT_LUA_FILE = os.path.join(DEFAULT_SYSBENCH_DIR, "share", "sysbench", "oltp_read_write.lua")


class MariaDBSysbenchSetup:
    """Sets up MariaDB and prepare sysbench OLTP tests"""

    def __init__(self, args):
        self.db_name = args.db_name
        self.db_user = args.db_user
        self.db_pass = args.db_pass
        self.port = args.port
        self.config_file = args.config_file
        self.config_dir = os.path.dirname(self.config_file)
        self.mysql_cmd = args.mysql_cmd
        self.threads = args.threads
        self.tables = args.tables
        self.table_size = args.table_size
        self.bench_time = args.time
        self.service = args.service
        self.sysbench_dir = args.sysbench_dir or DEFAULT_SYSBENCH_DIR
        self.lua_file = args.lua_file or DEFAULT_LUA_FILE
        self.ipv4 = args.host_ip or self._detect_ipv4()
        self.config_modified = False
        self.config = {}
        self._ensure_root()

    def run(self, cmd, *args, **kwargs):
        """Runs a command showing command line on errors"""
        try:
            return subprocess.run(cmd, *args, **kwargs)
        except subprocess.CalledProcessError:
            print(f"$ {' '.join(cmd)}")
            raise

    def _ensure_root(self):
        if os.geteuid() != 0:
            print("This script must be run as root.", file=sys.stderr)
            sys.exit(1)

    def _detect_ipv4(self):
        """Detect IPv4 prioritizing physical NICs, excluding docker/bridge/localhost."""
        try:
            res = self.run(["ip", "-4", "-br", "addr"], capture_output=True, text=True, check=True)

            addr = []
            for line in res.stdout.strip().splitlines():
                parts = line.split()
                if parts[1] == "DOWN":
                    continue

                match = re.match(r"(^\d+\.\d+\.\d+\.\d+)/\d+$", parts[2])
                if not match:
                    continue

                ip = match.group(1)

                if parts[0].startswith(("eth", "en", "eno", "ens", "em", "p", "wl", "enp")):
                    addr.insert(0, ip)
                else:
                    addr.append(ip)

            if not addr:
                ip = "127.0.0.1"
            else:
                ip = addr[0]

            return ip

        except Exception as e:
            print(
                f"Warning: IPv4 detection failed ({e}). Falling back to 127.0.0.1", file=sys.stderr
            )
            return "127.0.0.1"

    def _read_config_files(self):
        """Gather all MariaDB/MySQL configuration files to scan."""
        files = ["/etc/my.cnf"]

        config_dir = "/etc/my.cnf.d"
        if os.path.isdir(config_dir):
            for f in reversed(os.listdir(config_dir)):
                if f.endswith(".cnf"):
                    files.append(os.path.join(config_dir, f))

        if DEFAULT_CONFIG_FILE not in files:
            files.append(DEFAULT_CONFIG_FILE)

        for fname in files:
            config = configparser.ConfigParser(
                interpolation=None,
                strict=False,
                allow_no_value=True,
                comment_prefixes=("#", ";", "!"),
            )

            if os.path.isfile(fname):
                config.read(fname)

            self.config[fname] = {"config": config, "modified": False}

    def _set_config_var(self, section, key, value):
        """Update or add a key=value pair in config files. Returns True if modified."""
        old = None
        for fname, data in self.config.items():
            old = data["config"].get(section, key, fallback=None)
            if old:
                old = old.strip().strip("\"'")
                break

        if not old:
            fname = DEFAULT_CONFIG_FILE
        else:
            if old.isdigit() and value.isdigit():
                if int(old) == int(value):
                    return False
                if int(value) and int(old) > int(value):
                    return False
            if old == value:
                return False

        if not old:
            print(f"  {fname}: add at [{section}]: {key} = {value}")
        else:
            print(f"  {fname}: modify at [{section}]: {key} = {value}")

        config = self.config[fname]["config"]
        if section not in config:
            config.add_section(section)

        config.set(section, key, value)
        self.config[fname]["modified"] = True

    def _write_config_files(self):
        """Flush changes to configuration files"""

        changed = False

        for fname, data in self.config.items():
            if not data["modified"]:
                continue

            config = data["config"]
            with open(fname, "w", encoding="utf-8") as fp:
                config.write(fp)

            print(f"Wrote config {fname}")
            changed = True

        if changed:
            print(f"Config modified, restarting {self.service}...")
            res = self.run(["systemctl", "restart", self.service], check=True)
            if res.returncode:
                sys.exit(
                    f"{self.service} failed to start. Check journalctl -u {self.service} for details.",
                )

            sleep(5)

    def _manage_service(self):
        """Start/enable MariaDB/MySQL and handle restarts if config changed."""
        print(f"Enabling {self.service}...")
        self.run(["systemctl", "enable", "--now", self.service], check=True)

        res = self.run(["systemctl", "is-active", "--quiet", self.service], capture_output=True)
        if res.returncode:
            print("  Starting service...")
            res = self.run(["systemctl", "restart"], check=True)
            if res.returncode:
                sys.exit(
                    f"{self.service} failed to start. Check journalctl -u {self.service} for details.",
                )

            sleep(5)

    def _configure_database(self):
        """Create database, user, and grants."""
        print("Configuring database and user permissions...")
        sql = f"""
            DROP DATABASE IF EXISTS {self.db_name};
            DROP USER IF EXISTS '{self.db_user}'@'%';
            CREATE DATABASE {self.db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            CREATE USER '{self.db_user}'@'%' IDENTIFIED BY '{self.db_pass}';
            GRANT ALL PRIVILEGES ON {self.db_name}.* TO '{self.db_user}'@'%';
            FLUSH PRIVILEGES;
        """
        self.run([self.mysql_cmd, "-u", "root"], input=sql, check=True, text=True)

    def _run_sysbench(self):
        """Execute sysbench prepare and run phases."""
        env = os.environ.copy()
        cmd_base = [
            f"{self.sysbench_dir}/bin/sysbench",
            self.lua_file,
            f"--mysql-host={self.ipv4}",
            f"--mysql-port={self.port}",
            f"--mysql-db={self.db_name}",
            f"--mysql-user={self.db_user}",
            f"--mysql-password={self.db_pass}",
            f"--threads={self.threads}",
            f"--tables={self.tables}",
            f"--table-size={self.table_size}",
            f"--time={self.bench_time}",
        ]

        print("Preparing sysbench oltp_read_write...")
        prepare_cmd = cmd_base + ["prepare"]

        print(" ".join(prepare_cmd))
        res = self.run(prepare_cmd, env=env, capture_output=True, text=True)
        if res.returncode != 0:
            print("  (Note: sysbench prepare failed or was already prepared. Continuing... )")

        print("Running oltp_read_write...")
        run_cmd = cmd_base + ["run"]
        print(" ".join(run_cmd))
        self.run(run_cmd, env=env, check=True)

    def setup(self):
        """Orchestrate the full setup process."""
        self._manage_service()

        self._read_config_files()
        vars_to_set = [
            ("symbolic-links", "0"),
            ("max_connections", "100000"),
            ("max_user_connections", "0"),
            ("max_prepared_stmt_count", "100000"),
            ("bind-address", "0.0.0.0"),
            ("skip-networking", "0"),
        ]
        for k, v in vars_to_set:
            self._set_config_var("mysqld", k, v)
        self._write_config_files()

        self._configure_database()
        self._run_sysbench()

        print("\n====== Setup completed successfully! ======")
        print(f"Database:  {self.db_name}:{self.port}")
        print(f"User:      {self.db_user}")
        print(f"Password:  {self.db_pass}")
        print(f"Config:    {self.config_file}")
        print("==============================================")


def main():
    parser = argparse.ArgumentParser(description="Setup MariaDB/MySQL for Sysbench benchmarking")
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME, help="Database name")
    parser.add_argument("--db-user", default=DEFAULT_DB_USER, help="Database user")
    parser.add_argument("--db-pass", default=DEFAULT_DB_PASS, help="Database password")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MariaDB/MySQL port")
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE, help="Sysbench config path")
    parser.add_argument(
        "--sysbench-dir", default=DEFAULT_SYSBENCH_DIR, help="Sysbench installation directory"
    )
    parser.add_argument("--lua-file", default=DEFAULT_LUA_FILE, help="Path to oltp_read_write.lua")
    parser.add_argument(
        "--threads", type=int, default=DEFAULT_THREADS, help="Number of worker threads"
    )
    parser.add_argument("--tables", type=int, default=DEFAULT_TABLES, help="Number of tables")
    parser.add_argument("--table-size", type=int, default=DEFAULT_TABLE_SIZE, help="Rows per table")
    parser.add_argument(
        "--time", type=int, default=DEFAULT_BENCH_TIME, help="Benchmark duration in seconds"
    )
    parser.add_argument("--host-ip", default=None, help="Force IP address for MySQL connection")
    parser.add_argument("--mysql-cmd", help="MySQL client command (default: auto)")
    parser.add_argument("--service", help="MySQL client command (default: mariadb.service)")

    args = parser.parse_args()

    if not args.service:
        args.service = "mariadb.service"

    if not args.mysql_cmd:
        mysql = which("mariadb")
        if not mysql:
            mysql = which("mysql")

        if not mysql:
            sys.exit("Error: mysql/mariadb client not found!")

        args.mysql_cmd = mysql

    mysqlsetup = MariaDBSysbenchSetup(args)
    mysqlsetup.setup()


if __name__ == "__main__":
    main()
