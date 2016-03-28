import os
import subprocess
import sys
import re
import io
import shutil, stat
try:
    import urllib2
except ImportError:
    from urllib import request as urllib2
import tarfile


def on_rm_error(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    os.unlink(path)


got_tty = not os.environ.get('TERM', 'dumb') in ['dumb', 'emacs']
if got_tty:
	try:
		got_tty = sys.stderr.isatty() and sys.stdout.isatty()
	except AttributeError:
		got_tty = False

def get_term_cols():
	return 80
# If console packages are available, replace the dummy function with a real
# implementation
try:
	import struct, fcntl, termios
except ImportError:
	pass
else:
	if got_tty:
		def get_term_cols_real():
			"""
			Private use only.
			"""

			dummy_lines, cols = struct.unpack("HHHH", \
			fcntl.ioctl(sys.stdout.fileno(),termios.TIOCGWINSZ , \
			struct.pack("HHHH", 0, 0, 0, 0)))[:2]
			return cols
		# try the function once to see if it really works
		try:
			get_term_cols_real()
		except Exception:
			pass
		else:
			get_term_cols = get_term_cols_real

cols = get_term_cols()

platform_flags = {
    'darwin':   [],
    'win32':    ['-static-libgcc']#, '-static-libstdc++'],
}
env = os.environ.copy()
if 'CC' in env:
    gcc = env['CC']
else:
    gcc = 'gcc'
    gxx = 'g++'
    #env['CC'] = gcc
    #env['CXX'] = gxx
env['CFLAGS']   = ' '.join(platform_flags.get(sys.platform, []))
env['CXXFLAGS'] = ' '.join(platform_flags.get(sys.platform, []))
env['LDFLAGS']  = ' '.join(platform_flags.get(sys.platform, []))

def get_gcc_host():
    cmd = [gcc, '-v']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    target = None
    for line in p.stdout.readlines():
        if not isinstance(line, str):
            line = line.decode(errors='ignore')
        if line.startswith('Target'):
            target = line.strip().split()[1]
    return target


packages = [
    (
        'gmp',
        [
            ('http://ftp.gnu.org/gnu/gmp/gmp-6.0.0a.tar.bz2', '', None),
        ],
        [],
        True,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--prefix=%(install_path)s', '--enable-static', '--disable-shared'],
        ['make', '-j8'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'mpfr',
        [
            ('http://www.mpfr.org/mpfr-current/mpfr-3.1.4.tar.xz', '', None),
        ],
        [],
        True,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--prefix=%(install_path)s', '--enable-static', '--disable-shared',
                 '--with-gmp=%(install_path)s'],
        ['make', '-j8'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'mpc',
        [
            ('ftp://ftp.gnu.org/gnu/mpc/mpc-1.0.2.tar.gz', '', None),
        ],
        [],
        True,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--prefix=%(install_path)s', '--enable-static', '--disable-shared',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s'],
        ['make', '-j8'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'binutils',
        [
            ('http://ftp.gnu.org/gnu/binutils/binutils-2.26.tar.bz2', '', None)
        ],
        [
            ('binutils-2.24.patch', 1),
        ],
        False,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-static', '--disable-shared', '--with-gold', '--with-sysroot=%(sysroot_path)s',
                 '--enable-multiarch', '--disable-nls',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s'],
        ['make', '-j8'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'gcc-4.9',
        [
            ('ftp://ftp.fu-berlin.de/unix/languages/gcc/releases/gcc-4.9.3/gcc-4.9.3.tar.bz2', '', None)
        ],
        [
            ('gcc-4.9.2.patch', 2),
        ],
        False,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-static', '--enable-shared', '--enable-multiarch', '--disable-nls', '--disable-sjlj',
                 '--enable-objc-gc', '--enable-languages=c,c++,objc,obj-c++',
                 '--with-sysroot=%(sysroot_path)s', '--with-build-sysroot=%(sysroot_path)s',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--program-prefix=%(target)s-', '--program-suffix=-4.9'],
        ['make', '-j2'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'gcc-5.3',
        [
            ('ftp://ftp.irisa.fr/pub/mirrors/gcc.gnu.org/gcc/releases/gcc-5.3.0/gcc-5.3.0.tar.bz2', '', None)
        ],
        [
            ('gcc-4.9.2.patch', 2),
        ],
        False,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-static', '--enable-shared', '--enable-multiarch', '--disable-nls', '--disable-sjlj',
                 '--enable-objc-gc', '--enable-languages=c,c++,objc,obj-c++',
                 '--with-sysroot=%(sysroot_path)s', '--with-build-sysroot=%(sysroot_path)s',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--program-prefix=%(target)s-', '--program-suffix=-5.3'],
        ['make', '-j2'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'clang-3.4',
        [
            ('http://llvm.org/releases/3.4.2/llvm-3.4.2.src.tar.gz', '', None),
            ('http://llvm.org/releases/3.4.2/cfe-3.4.2.src.tar.gz', 'llvm-3.4.2.src/tools', 'clang'),
            ('http://llvm.org/releases/3.4/compiler-rt-3.4.src.tar.gz', 'llvm-3.4.2.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.4.0.patch', 2)
        ],
        False,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s/lib/llvm-%(arch)s-3.4/',
                 '--enable-static', '--disable-shared', '--enable-optimized=yes', '--enable-assertions=no',  '--enable-threads=yes',
                 '--enable-debug-symbols=no', '--enable-docs=no', '--program-prefix=', '--enable-targets=all',
                 '--with-sysroot=%(sysroot_path)s', '--with-default-sysroot=%(sysroot_path)s', '--enable-pthreads=no',
                 '--with-gcc-toolchain=%(install_path)s/', '--with-python=%(install_path)s/bin/python.exe'],
        ['make', '-j8'],
        ['make', 'install'],
        ['make', 'clean'],
    ),
    (
        'clang-3.5',
        [
            ('http://llvm.org/releases/3.5.2/llvm-3.5.2.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.5.2/cfe-3.5.2.src.tar.xz', 'llvm-3.5.2.src/tools', 'clang'),
            ('http://llvm.org/releases/3.5.2/compiler-rt-3.5.2.src.tar.xz', 'llvm-3.5.2.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.5.0.patch', 1)
        ],
        False,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s/lib/llvm-%(arch)s-3.5/',
                 '--enable-static', '--disable-shared', '--enable-optimized=yes', '--enable-assertions=no',  '--enable-threads=yes',
                 '--enable-debug-symbols=no', '--enable-docs=no', '--program-prefix=', '--enable-targets=all',
                 '--with-sysroot=%(sysroot_path)s', '--with-default-sysroot=%(sysroot_path)s', '--enable-pthreads=no',
                 '--with-gcc-toolchain=%(install_path)s/', '--with-python=%(install_path)s/bin/python.exe'],
        ['make', '-j8'],
        ['make', 'install'],
        ['make', 'clean'],
    ),
    (
        'clang-3.6',
        [
            ('http://llvm.org/releases/3.6.2/llvm-3.6.2.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.6.2/cfe-3.6.2.src.tar.xz', 'llvm-3.6.2.src/tools', 'clang'),
            ('http://llvm.org/releases/3.6.2/compiler-rt-3.6.2.src.tar.xz', 'llvm-3.6.2.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.6.0.patch', 1)
        ],
        False,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s/lib/llvm-%(arch)s-3.6/',
                 '--enable-static', '--disable-shared', '--enable-optimized=yes', '--enable-assertions=no',  '--enable-threads=yes',
                 '--enable-debug-symbols=no', '--enable-docs=no', '--program-prefix=', '--enable-targets=all',
                 '--with-sysroot=%(sysroot_path)s', '--with-default-sysroot=%(sysroot_path)s', '--enable-pthreads=no',
                 '--with-gcc-toolchain=%(install_path)s/', '--with-python=%(install_path)s/bin/python.exe'],
        ['make', '-j8'],
        ['make', 'install'],
        ['make', 'clean'],
    ),
    (
        'clang-3.7',
        [
            ('http://llvm.org/releases/3.7.1/llvm-3.7.1.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.7.1/cfe-3.7.1.src.tar.xz', 'llvm-3.7.1.src/tools', 'clang'),
            ('http://llvm.org/releases/3.7.1/compiler-rt-3.7.1.src.tar.xz', 'llvm-3.7.1.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.7.0.patch', 1)
        ],
        False,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s/lib/llvm-%(arch)s-3.7/',
                 '--enable-static', '--disable-shared', '--enable-optimized=yes', '--enable-assertions=no',  '--enable-threads=yes',
                 '--enable-debug-symbols=no', '--enable-docs=no', '--program-prefix=', '--enable-targets=all',
                 '--with-sysroot=%(sysroot_path)s', '--with-default-sysroot=%(sysroot_path)s', '--enable-pthreads=no',
                 '--with-gcc-toolchain=%(install_path)s/', '--with-python=%(install_path)s/bin/python.exe'],
        ['make', '-j8'],
        ['make', 'install'],
        ['make', 'clean'],
    ),
    (
        'clang-3.8',
        [
            ('http://llvm.org/releases/3.8.0/llvm-3.8.0.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.8.0/cfe-3.8.0.src.tar.xz', 'llvm-3.8.0.src/tools', 'clang'),
            ('http://llvm.org/releases/3.8.0/compiler-rt-3.8.0.src.tar.xz', 'llvm-3.8.0.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.7.0.patch', 1)
        ],
        False,
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s/lib/llvm-%(arch)s-3.8/',
                 '--enable-static', '--disable-shared', '--enable-optimized=yes', '--enable-assertions=no',  '--enable-threads=yes',
                 '--enable-debug-symbols=no', '--enable-docs=no', '--program-prefix=', '--enable-targets=all',
                 '--with-sysroot=%(sysroot_path)s', '--with-default-sysroot=%(sysroot_path)s', '--enable-pthreads=no',
                 '--with-gcc-toolchain=%(install_path)s/', '--with-python=%(install_path)s/bin/python.exe'],
        ['make', '-j8'],
        ['make', 'install'],
        ['make', 'clean'],
    )
]


def download_pkg(url):
    def chunk_report(bytes_so_far, chunk_size, total_size):
        if total_size:
            percent = float(bytes_so_far) / total_size
            percent = round(percent*100, 2)
            sys.stdout.write('\r[%0.2f%%] %s...'%(percent, url))
            sys.stdout.flush()
        else:
            data_so_far = float(bytes_so_far)
            unit = 'B'
            if data_so_far > 1024*5:
                data_so_far = data_so_far / 1024
                unit = 'kB'
            if data_so_far > 1024*5:
                data_so_far = data_so_far / 1024
                unit = 'MB'
            sys.stdout.write('\r[%0.2f%s] %s...'%(data_so_far, unit, url))
            sys.stdout.flush()
    chunk_size = 8192*8
    data = bytes()
    response = urllib2.urlopen(url)
    try:
        total_size = response.info()['Content-length'].strip()
        total_size = int(total_size)
    except Exception as e:
        print(e)
        total_size = 0
    bytes_so_far = 0
    chunk_report(bytes_so_far, chunk_size, total_size)
    while(1):
        try:
            chunk = response.read(chunk_size)
            bytes_so_far += len(chunk)
            if not chunk:
                break
            data += chunk
            chunk_report(bytes_so_far, chunk_size, total_size)
        except Exception as e:
            print(e)
            return None
    print('')
    return data


def extract_pkg(data, dest, rename):
    tar = tarfile.open(fileobj=io.BytesIO(data))
    root = tar.next()
    root_dir = root.name.split('/')[0]
    print('unpacking...')
    tar.extractall('src/%s' % dest)
    if rename:
        os.rename(os.path.join('src', dest, root_dir), os.path.join('src', dest, rename))
        root_dir = rename
    return os.path.join(dest, root_dir)


def patch_pkg(src_root_dir, patch, patch_level):
    print('applying %s...' % patch)
    with open(os.path.join('patches', patch), 'rb') as patchfile:
        p = subprocess.Popen(['patch', '-p', str(patch_level)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=src_root_dir)
        p.stdin.write(patchfile.read())
        out, err = p.communicate()
        p.stdin.close()
        if p.returncode != 0:
            if not isinstance(out, str):
                out = out.decode(errors='ignore')
            raise Exception('failed to patch: %s' % out)


def run(command, bld_dir, step, config):
    print('running %s step...' % step)
    with open('bld/%s.log'%step, 'w') as logfile:
        run_command = [i % config for i in command]
        p = subprocess.Popen(run_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=bld_dir, env=env)
        line=p.stdout.readline()
        while line:
            if not isinstance(line, str):
                line = line.decode(errors='ignore')
            logfile.write(line)
            line = line.rstrip()
            length = len(line)
            if length+2 > cols:
                sys.stdout.write('\r=>%s...' % line[:cols-5])
            else:
                sys.stdout.write('\r=>%s%s' % (line, ' '*(cols-length-2)))
            line=p.stdout.readline()
        p.communicate()
        sys.stdout.write('\r%s\r' % (' '*(cols+2)))
        if p.returncode != 0:
            raise Exception('failed to run %s step, check log file for more information' % step)


def build(bld_dir, configure_cmd, build_cmd, install_cmd, clean_cmd, archs):
    if archs:
        for arch in archs:
            config['arch'] = arch
            config['target'] = '%s-pc-linux-gnu'%arch
            config['src_path'] = src_root_dir
            run(configure_cmd, bld_root_dir, 'configure', config)
            run(build_cmd, bld_root_dir, 'build', config)
            run(install_cmd, bld_root_dir, 'install', config)
            run(clean_cmd, bld_root_dir, 'clean', config)
    else:
        config['src_path'] = src_root_dir
        run(configure_cmd, bld_root_dir, 'configure', config)
        run(build_cmd, bld_root_dir, 'build', config)
        run(install_cmd, bld_root_dir, 'install', config)
        run(clean_cmd, bld_root_dir, 'clean', config)


if __name__ == '__main__':
    config = {
        'install_path': os.path.abspath('pc-linux-gnu').replace('\\', '/'),
        'sysroot_path': os.path.abspath('pc-linux-gnu/sysroot').replace('\\', '/'),
        'host':         get_gcc_host(),
    }
    archs = [
        'x86_64',
        'powerpc',
        #'armel',
        #'armhf',
        #'aarch64',
        #'mips',
        #'mipsel',
        ]
    do_build = sys.argv[1:]

    for package_name, package_urls, patch_list, is_host_build, configure_cmd, build_cmd, install_cmd, clean_cmd in packages:
        if do_build and package_name not in do_build:
            continue
        root_dir = None
        try:
            try: os.mkdir('src')
            except OSError: pass
            try: os.mkdir('bld')
            except OSError: pass
            for url, dest, rename in package_urls:
                data = download_pkg(url)
                root_dir_pkg = extract_pkg(data, dest, rename)
                root_dir = root_dir or root_dir_pkg
            src_root_dir = '../../src/%s' % root_dir
            bld_root_dir = os.path.abspath(os.path.join('bld', root_dir))
            try: os.mkdir(bld_root_dir)
            except OSError: pass
            for patch, patch_level in patch_list:
                patch_pkg('src/%s'%root_dir, patch, patch_level)
            build(bld_root_dir, configure_cmd, build_cmd, install_cmd, clean_cmd, [] if is_host_build else archs)
        except Exception as e:
            raise e
        else:
            shutil.rmtree('bld', onerror=on_rm_error)
            shutil.rmtree('src', onerror=on_rm_error)

