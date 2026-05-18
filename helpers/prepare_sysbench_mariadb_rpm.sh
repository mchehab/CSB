#!/usr/bin/env bash
set -euo pipefail

# Requires:
# mariadb-devel

# =============
# Configuration
# =============

DB_NAME="sbtest"
DB_USER="sbtest"
DB_PASS="${DB_PASS:-Password@123}"
IPv4=$(ip -4 -br addr|grep UP|head -1|perl -ne 'print "$1\n" if (m/(\d+\.\d+\.\d+\.\d+)/)')
PORT=3306
CONFIG_FILE="/etc/my.cnf.d/sysbench.cnf"

MYSQL_CMD="mariadb"

SCRIPT_DIR="$(readlink -f $(dirname "$0")/..)"
SYSBENCH_DIR="${SCRIPT_DIR}/bm-external/sysbench"
LUA="${SYSBENCH_DIR}/share/sysbench/oltp_read_write.lua"
PATH="${SYSBENCH_DIR}/bin:${PATH}"

# =========================
# Check for root privileges
# =========================
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root."
    exit 1
fi

# ========================================
# Ancillary logit to handle MariaDB config
# ========================================
mkdir -p "/etc/my.cnf.d/"
touch "$CONFIG_FILE"

CONFIG_MODIFIED=false

set_config_var() {
    local key="$1"
    local value="$2"
    local target_file=$CONFIG_FILE
    local found=false

    # Safely gather all MariaDB config sources
    shopt -s nullglob
    local conf_files=("/etc/my.cnf" "/etc/my.cnf.d/*.cnf")
    shopt -u nullglob

    for conf in "${conf_files[@]}"; do
        if [ ! -f "$conf" ]; then
            continue
        fi

        if grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$conf" 2>/dev/null; then
            found=true
            # MariaDB uses the LAST occurrence, so we extract the last value
            local current_val
            current_val=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$conf" | tail -1 | sed -E "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//" | xargs)

            # "Equal or better" logic
            local update=false
            if [[ "$current_val" =~ ^[1-9][0-9]*$ ]] && [[ "$value" =~ ^[0-9]+$ ]]; then
                (( current_val >= value )) && update=true
            elif [[ "$current_val" == "$value" ]]; then
                update=true
            fi

            if $update; then
                echo "  Updating $key in ${current_val}"
                sed -i -E "s/^[[:space:]]*${key}[[:space:]]*=.*/${key} = ${value}/" "$conf"
                CONFIG_MODIFIED=true
            fi
        fi
    done

   if ! $found; then
       if ! grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$target_file" 2>/dev/null; then
           if grep -q "^\[mysqld\]" "$target_file" 2>/dev/null; then
               awk -v key="$key" -v val="$value" '
                   /^\[mysqld\]/ { print; print key " = " val; next }
                   { print }
               ' "$target_file" > "${target_file}.tmp" && mv "${target_file}.tmp" "$target_file"
           else
               # Prepend [mysqld] section at the top if completely missing
               { echo "[mysqld]"; echo "${key} = ${value}"; cat "$target_file"; } > "${target_file}.tmp" && mv "${target_file}.tmp" "$target_file"
           fi
           CONFIG_MODIFIED=true
       fi
   fi
}

# ==========================================
# Configure MariaDB to work with sysbench
# ==========================================
set_config_var "symbolic-links" "0"
set_config_var "max_connections" "100000"
set_config_var "max_user_connections" "0"
set_config_var "max_prepared_stmt_count" "100000"
set_config_var "bind-address" "0.0.0.0"
set_config_var "skip-networking" "0"

# =============
# Start MariaDB
# =============
echo "Starting and enabling MariaDB service with needed settings..."
systemctl enable --now mariadb.service 2>/dev/null || true

if $CONFIG_MODIFIED; then
    systemctl restart mariadb.service
    sleep 3
fi

# Verify service is active
if ! systemctl is-active --quiet mariadb.service; then
    echo "MariaDB failed to start. Check journalctl -u mariadb.service for details."
    exit
fi

# ==============================
# Create Database, User & Grants
# ==============================
echo "Configuring MariaDB database and user permissions..."

${MYSQL_CMD} -u root <<EOF
DROP DATABASE IF EXISTS ${DB_NAME};
DROP USER IF EXISTS '${DB_USER}'@'%';
CREATE DATABASE ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
EOF

# ================================
# Run sysbench prepare and test it
# ================================
echo "Preparing sysbench oltp_read_write..."
set -x
sysbench $LUA --mysql-host=${IPv4} --mysql-port=${PORT} \
         --mysql-db=${DB_NAME} --mysql-user=${DB_USER} \
         --mysql-password=${DB_PASS} \
         --threads=1 --tables=3 --table-size=10000 --time=1 \
         prepare || echo "Failed (maybe already prepared?)"
set +x

echo "Running oltp_read_write..."
sysbench $LUA --mysql-host=${IPv4} --mysql-port=${PORT} \
         --mysql-db=${DB_NAME} --mysql-user=${DB_USER} \
         --mysql-password=${DB_PASS} \
         --threads=1 --tables=3 --table-size=10000 --time=1 \
         run

echo
echo "========================================"
echo "Setup completed successfully!"
echo "Database:  ${DB_NAME}:${PORT}"
echo "User:      ${DB_USER}"
echo "Password:  ${DB_PASS}"
echo "Config:    ${CONFIG_FILE}"
echo "========================================"
echo
