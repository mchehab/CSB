#!/usr/bin/env python3
"""
MariaDB/MySQL + Sysbench Setup Script
- All configuration via argparse (all optional)
- Defaults defined as module-level constants
- Strict os.path usage (no pathlib)
- configparser for INI handling
- Smart IP detection prioritizing physical NICs
- Auto SSL generation with -batch flag
- --force-ssl support
- Class-based architecture
"""

import argparse
import os
import sys
import subprocess
import configparser
import re
import stat

# === Configuration Defaults ===
DEFAULT_DB_NAME = "sbtest"
DEFAULT_DB_USER = "sbtest"
DEFAULT_DB_PASS = "Password@123"
DEFAULT_PORT = 3306
DEFAULT_CONFIG_FILE = "/etc/my.cnf.d/sysbench.cnf"
DEFAULT_THREADS = 1
DEFAULT_TABLES = 3
DEFAULT_TABLE_SIZE = 10000
DEFAULT_BENCH_TIME = 1
DEFAULT_MYSQL_CMD = "mariadb"

DEFAULT_SYSBENCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "bm-external", "sysbench")
DEFAULT_LUA_FILE = os.path.join(DEFAULT_SYSBENCH_DIR,
                                "share", "sysbench", "oltp_read_write.lua")

class MariaDBSysbenchSetup:
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
        self.sysbench_dir = args.sysbench_dir or DEFAULT_SYSBENCH_DIR
        self.lua_file = args.lua_file or DEFAULT_LUA_FILE
        self.ipv4 = args.host_ip or self._detect_ipv4()
        self.config_modified = False
        self.force_ssl = args.force_ssl
        self._ensure_root()

    def _ensure_root(self):
        if os.geteuid() != 0:
            print("This script must be run as root.", file=sys.stderr)
            sys.exit(1)

    def _detect_ipv4(self):
        """Detect IPv4 prioritizing physical NICs, excluding docker/bridge/localhost."""
        try:
            res = subprocess.run(['ip', '-4', '-br', 'addr'], capture_output=True, text=True, check=True)
            primary_candidates = []
            fallback_candidates = []

            for line in res.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) < 4 or parts[1] != 'UP':
                    continue

                ip_match = None
                for p in parts:
                    if re.match(r'^\d+\.\d+\.\d+\.\d+/\d+$', p):
                        ip_match = p
                        break
                if not ip_match:
                    continue

                ip = ip_match.split('/')[0]
                iface = parts[0]

                if ip == '127.0.0.1':
                    continue
                if iface.startswith(('docker', 'br-', 'veth', 'lo')):
                    fallback_candidates.append((iface, ip))
                    continue

                priority = 10
                if iface.startswith(('eth', 'en', 'eno', 'ens', 'em', 'p', 'wl', 'enp')):
                    priority = 10
                primary_candidates.append((iface, ip, priority))

            if primary_candidates:
                primary_candidates.sort(key=lambda x: x[2], reverse=True)
                return primary_candidates[0][1]
            if fallback_candidates:
                return fallback_candidates[0][1]
            return '127.0.0.1'
        except Exception as e:
            print(f"Warning: IPv4 detection failed ({e}). Falling back to 127.0.0.1", file=sys.stderr)
            return '127.0.0.1'

    def _get_config_files(self):
        """Gather all MariaDB/MySQL configuration files to scan."""
        files = ['/etc/my.cnf']
        config_dir = '/etc/my.cnf.d'
        if os.path.isdir(config_dir):
            for f in os.listdir(config_dir):
                if f.endswith('.cnf'):
                    files.append(os.path.join(config_dir, f))
        return files

    def _set_config_var(self, key, value):
        """Update or add a key=value pair in config files. Returns True if modified."""
        files = self._get_config_files()
        found_keys = []

        for conf_file in files:
            if not os.path.isfile(conf_file):
                continue

            # Try configparser first
            config = configparser.ConfigParser(interpolation=None, comment_prefixes=('#', ';', '!'))
            config.read(conf_file)
            val_found = False
            for section in config.sections():
                if config.has_option(section, key):
                    found_keys.append((conf_file, config.get(section, key).strip().strip('"\'')))
                    val_found = True
                    break

            if not val_found:
                 raise ValueError(f"Can't handle {config_file}")

        if not found_keys:
            should_update = True
        else:
            _, last_val = found_keys[-1]
            is_numeric = last_val.isdigit() and value.isdigit()
            if is_numeric and int(last_val) >= int(value):
                print(f"  {key} is already {last_val} (>= {value}), no update needed.")
                return False
            elif last_val == value:
                print(f"  {key} is already {value}, no update needed.")
                return False
            else:
                should_update = True

        print(f"  Updating {key} to {value}")
        self.config_modified = True

        # Update the file where the last occurrence was
        target_file = found_keys[-1][0] if found_keys else self.config_file
        lines = open(target_file, 'r').read().splitlines()
        updated_lines = []
        modified = False
        for line in lines:
            stripped = line.lstrip()
            if re.match(rf'^{re.escape(key)}\s*=', stripped):
                updated_lines.append(f"{key} = {value}")
                modified = True
            else:
                updated_lines.append(line)
        if modified:
            open(target_file, 'w').write('\n'.join(updated_lines) + '\n')
            return True

        # Add to target config if not found anywhere
        os.makedirs(self.config_dir, exist_ok=True)
        open(target_file, 'a').write('\n')
        content = open(target_file, 'r').read()
        if not re.search(r'\[mysqld\]', content):
            content = f"[mysqld]\n{key} = {value}\n"
        else:
            content = re.sub(r'(\[mysqld\])', rf'\1\n{key} = {value}', content, count=1)
        open(target_file, 'w').write(content)
        return True

    def _setup_ssl(self):
        """Check SSL status and generate certificates if disabled or forced."""
        ssl_ca = '/etc/mysql/ssl/ca.pem'
        ssl_cert = '/etc/mysql/ssl/server-cert.pem'
        ssl_key = '/etc/mysql/ssl/server-key.pem'

        if not self.force_ssl:
            # Check if SSL is already configured
            for f in self._get_config_files():
                if os.path.isfile(f):
                    content = open(f).read()
                    if 'ssl-ca' in content or 'require_secure_transport' in content:
                        print("  SSL is already enabled. Skip generation. Use --force-ssl to override.")
                        return

        print("  Enabling SSL and generating self-signed certificates...")
        ssl_dir = os.path.dirname(ssl_ca)
        os.makedirs(ssl_dir, exist_ok=True)

        # Generate CA (with -batch to avoid interactive prompts)
        subprocess.run(['openssl', 'req', '-batch', '-new', '-x509', '-days', '3650', '-nodes', '-out', ssl_ca, '-keyout', ssl_ca, '-subj', '/CN=MariaDB CA'], check=True)
        # Generate Server Cert
        subprocess.run(['openssl', 'req', '-batch', '-new', '-nodes', '-out', ssl_cert + '.csr', '-keyout', ssl_key, '-subj', '/CN=mariadb-server'], check=True)
        subprocess.run(['openssl', 'x509', '-req', '-in', ssl_cert + '.csr', '-CA', ssl_ca, '-CAkey', ssl_ca, '-CAcreateserial', '-out', ssl_cert, '-days', '3650'], check=True)

        # Cleanup CSR & serial
        for p in [ssl_cert + '.csr', ssl_ca + '.srl']:
            if os.path.exists(p):
                os.remove(p)

        os.chmod(ssl_key, stat.S_IRUSR | stat.S_IWUSR)
        os.chmod(ssl_cert, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        os.chmod(ssl_ca, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

        self._set_config_var('ssl-ca', ssl_ca)
        self._set_config_var('ssl-cert', ssl_cert)
        self._set_config_var('ssl-key', ssl_key)
        self._set_config_var('require_secure_transport', 'ON')
        print("  SSL configuration applied.")

    def _manage_service(self):
        """Start/enable MariaDB/MySQL and handle restarts if config changed."""
        print("Starting and enabling MariaDB/MySQL service...")
        subprocess.run(['systemctl', 'enable', '--now', 'mariadb.service'], check=False)

        if self.config_modified:
            print("  Config modified, restarting service...")
            subprocess.run(['systemctl', 'restart', 'mariadb.service'], check=False)
            subprocess.run(['sleep', '3'], check=True)

        res = subprocess.run(['systemctl', 'is-active', '--quiet', 'mariadb.service'], capture_output=True)
        if res.returncode != 0:
            print("MariaDB/MySQL failed to start. Check journalctl -u mariadb.service for details.", file=sys.stderr)
            sys.exit(1)

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
        subprocess.run([self.mysql_cmd, '-u', 'root'], input=sql, check=True, text=True)

    def _run_sysbench(self):
        """Execute sysbench prepare and run phases."""
        env = os.environ.copy()
        env['PATH'] = f"{self.sysbench_dir}/bin:{env['PATH']}"
        cmd_base = [
            'sysbench', self.lua_file,
            f'--mysql-host={self.ipv4}', f'--mysql-port={self.port}',
            f'--mysql-db={self.db_name}', f'--mysql-user={self.db_user}',
            f'--mysql-password={self.db_pass}',
            f'--threads={self.threads}', f'--tables={self.tables}',
            f'--table-size={self.table_size}', f'--time={self.bench_time}'
        ]

        print("Preparing sysbench oltp_read_write...")
        prepare_cmd = cmd_base + ['prepare']
        res = subprocess.run(prepare_cmd, env=env, capture_output=True, text=True)
        if res.returncode != 0:
            print("  (Note: sysbench prepare failed or was already prepared. Continuing. .)")

        print("Running oltp_read_write...")
        run_cmd = cmd_base + ['run']
        subprocess.run(run_cmd, env=env, check=True)

    def run(self):
        """Orchestrate the full setup process."""
        self._manage_service()
        self._setup_ssl()

        vars_to_set = [
            ("symbolic-links", "0"),
            ("max_connections", "100000"),
            ("max_user_connections", "0"),
            ("max_prepared_stmt_count", "100000"),
            ("bind-address", "0.0.0.0"),
            ("skip-networking", "0")
        ]
        for k, v in vars_to_set:
            self._set_config_var(k, v)

        self._configure_database()
        self._run_sysbench()

        print("\n====== Setup completed successfully! ======")
        print(f"Database:  {self.db_name}:{self.port}")
        print(f"User:      {self.db_user}")
        print(f"Password:  {self.db_pass}")
        print(f"Config:    {self.config_file}")
        print("============================================")


def main():
    parser = argparse.ArgumentParser(description="Setup MariaDB/MySQL for Sysbench benchmarking")
    parser.add_argument('--db-name', default=DEFAULT_DB_NAME, help='Database name')
    parser.add_argument('--db-user', default=DEFAULT_DB_USER, help='Database user')
    parser.add_argument('--db-pass', default=DEFAULT_DB_PASS, help='Database password')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='MariaDB/MySQL port')
    parser.add_argument('--config-file', default=DEFAULT_CONFIG_FILE, help='Sysbench config path')
    parser.add_argument('--sysbench-dir', default=DEFAULT_SYSBENCH_DIR, help='Sysbench installation directory')
    parser.add_argument('--lua-file', default=DEFAULT_LUA_FILE, help='Path to oltp_read_write.lua')
    parser.add_argument('--threads', type=int, default=DEFAULT_THREADS, help='Number of worker threads')
    parser.add_argument('--tables', type=int, default=DEFAULT_TABLES, help='Number of tables')
    parser.add_argument('--table-size', type=int, default=DEFAULT_TABLE_SIZE, help='Rows per table')
    parser.add_argument('--time', type=int, default=DEFAULT_BENCH_TIME, help='Benchmark duration in seconds')
    parser.add_argument('--host-ip', default=None, help='Force IP address for MySQL connection')
    parser.add_argument('--mysql-cmd', default=DEFAULT_MYSQL_CMD, help='MySQL client command (default: mariadb)')
    parser.add_argument('--force-ssl', action='store_true', help='Force SSL certificate re-creation')

    args = parser.parse_args()
    setup = MariaDBSysbenchSetup(args)
    setup.run()

if __name__ == '__main__':
    main()
