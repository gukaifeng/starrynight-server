#!/usr/bin/env bash
# Rootless runtime for Ubuntu x86_64. Does not start or stop application services.
set -euo pipefail
umask 077
deploy_root="${1:-$HOME/app}"
mkdir -p "$deploy_root"/{bin,cache,build,logs}
cd "$deploy_root/cache"
if [ ! -f "$deploy_root/build/sysroot/usr/include/openssl/ssl.h" ] || [ ! -x "$deploy_root/build/sysroot/usr/bin/m4" ]; then
    apt-get download libssl-dev bison flex libfl2 m4
    mkdir -p "$deploy_root/build/sysroot"
    for archive in libssl-dev_*.deb bison_*.deb flex_*.deb libfl2_*.deb m4_*.deb; do
        dpkg-deb -x "$archive" "$deploy_root/build/sysroot"
    done
fi
deploy_include="$deploy_root/build/sysroot/usr/include"
deploy_lib="$deploy_root/build/sysroot/usr/lib/x86_64-linux-gnu"
for library in libssl.so.3 libcrypto.so.3; do
    if [ ! -e "$deploy_lib/$library" ]; then
        ln -s "/usr/lib/x86_64-linux-gnu/$library" "$deploy_lib/$library"
    fi
done
export PATH="$deploy_root/build/sysroot/usr/bin:$PATH"
export BISON_PKGDATADIR="$deploy_root/build/sysroot/usr/share/bison"
export M4="$deploy_root/build/sysroot/usr/bin/m4"
if [ ! -x "$deploy_root/postgres/bin/postgres" ]; then
    if [ ! -f postgresql-17.11.tar.bz2 ]; then
        curl -fL --retry 3 -o postgresql-17.11.tar.bz2.part https://ftp.postgresql.org/pub/source/v17.11/postgresql-17.11.tar.bz2
        mv postgresql-17.11.tar.bz2.part postgresql-17.11.tar.bz2
    fi
    curl -fL --retry 3 -o postgresql-17.11.tar.bz2.sha256 https://ftp.postgresql.org/pub/source/v17.11/postgresql-17.11.tar.bz2.sha256
    sha256sum -c postgresql-17.11.tar.bz2.sha256
    tar -xf postgresql-17.11.tar.bz2 -C "$deploy_root/build"
    cd "$deploy_root/build/postgresql-17.11"
    ./configure --prefix="$deploy_root/postgres" --without-readline --without-icu --with-openssl CPPFLAGS="-I$deploy_include -I$deploy_include/x86_64-linux-gnu" LDFLAGS="-L$deploy_lib"
    make -j2
    make install
    make -C contrib/pg_trgm install
fi
cd "$deploy_root/cache"
if [ ! -x "$deploy_root/bin/redis-server" ]; then
    if [ ! -f redis-8.10.2.tar.gz ]; then
        curl -fL --retry 3 -o redis-8.10.2.tar.gz.part https://github.com/redis/redis/archive/refs/tags/8.10.2.tar.gz
        mv redis-8.10.2.tar.gz.part redis-8.10.2.tar.gz
    fi
    tar -xf redis-8.10.2.tar.gz -C "$deploy_root/build"
    make -C "$deploy_root/build/redis-8.10.2" -j2 BUILD_TLS=yes MALLOC=libc OPT=-O2 CFLAGS="-I$deploy_include -I$deploy_include/x86_64-linux-gnu" LDFLAGS="-L$deploy_lib"
    install -m 755 "$deploy_root/build/redis-8.10.2/src/redis-server" "$deploy_root/bin/redis-server"
    install -m 755 "$deploy_root/build/redis-8.10.2/src/redis-cli" "$deploy_root/bin/redis-cli"
fi
cd "$deploy_root/cache"
if [ ! -x "$deploy_root/bin/caddy" ]; then
    # Use the distribution package; keep this path unchanged after setcap.
    apt-get download caddy
    for archive in caddy_*.deb; do dpkg-deb -x "$archive" "$deploy_root/build/sysroot"; done
    install -m 755 "$deploy_root/build/sysroot/usr/bin/caddy" "$deploy_root/bin/caddy"
fi
printf 'Runtime binaries prepared in %s\n' "$deploy_root"
