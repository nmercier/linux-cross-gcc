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
try:
    from hashlib import md5
except ImportError:
    from md5 import md5

cols = 80

target_platforms = (
    ('linux-gnu', 'linux-gnu'),
    ('freebsd', 'freebsd9.0'),
)

platform_flags = {
    'darwin':   [],
    'win32':    [],
}
env = os.environ.copy()
if 'CC' in env:
    gcc = env['CC']
    gxx = env['CXX']
elif sys.platform == 'win32':
    gcc = 'gcc'
    gxx = 'g++'
else:
    gcc=''
    gxx=''
    #env['CC'] = gcc
    #env['CXX'] = gxx
env['CFLAGS']   = ' '.join(platform_flags.get(sys.platform, []) + [env.get('CFLAGS', '')])
env['CXXFLAGS'] = ' '.join(platform_flags.get(sys.platform, []) + [env.get('CXXFLAGS', '')])
env['LDFLAGS']  = ' '.join(platform_flags.get(sys.platform, []) + [env.get('LDFLAGS', '')])
for target_platform, _ in target_platforms:
    env['PATH'] = env['PATH'] + os.pathsep + os.path.abspath('pc-%s/bin' % target_platform).replace('\\', '/')


def get_supported_archs(platform, sysroot):
    result = []
    if platform == 'linux-gnu':
        try:
            all_files = os.listdir(os.path.join(sysroot, 'lib'))
        except OSError:
            raise Exception("Is sysroot installed in %s?" % sysroot)
        else:
            for l in all_files:
                if l.find('linux-gnu') > 0 and os.path.isdir(os.path.join(sysroot, 'lib', l)):
                    arch = l.split('-')[0]
                    result.append((arch, l))
    elif platform == 'freebsd':
        result.append(['x86_64', 'x86_64-pc-freebsd9.0'])
    else:
        raise Exception("Don't know how to read supproted archs for target %s" % platform)
    return result


def get_gcc_host():
    cmd = [gcc, '-v']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    target = None
    for line in p.stdout.readlines():
        if not isinstance(line, str):
            line = line.decode(sys.stdout.encoding, errors='ignore')
        if line.startswith('Target'):
            target = line.strip().split()[1]
    return target


def make_dir(d):
    try:
        os.makedirs(d)
    except OSError:
        pass


def del_dir(d):
    def on_rm_error(func, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        os.unlink(path)
    if os.path.isdir(d):
        shutil.rmtree(d, onerror=on_rm_error)


packages = [
    (
        'prerequisites',
        [],
        [],
        True,
        [],
        [],
        {},
        [],
        ['bash', '-c', 'if [[ -d ../../../%(os)s ]]; then cp -vaR ../../../%(os)s/* %(install_path)s; fi'],
        [],
    ),
    (
        'gmp',
        [
            ('http://ftp.gnu.org/gnu/gmp/gmp-6.0.0a.tar.bz2', '', None),
        ],
        [],
        True,
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--prefix=%(install_path)s', '--disable-shared', '--enable-static'],
        {},
        ['make', '-j'],
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
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--prefix=%(install_path)s', '--disable-shared', '--enable-static',
                 '--with-gmp=%(install_path)s'],
        {},
        ['make', '-j'],
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
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--prefix=%(install_path)s', '--disable-shared', '--enable-static',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s'],
        {},
        ['make', '-j'],
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
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-static', '--disable-shared', '--enable-gold', '--with-sysroot=%(sysroot_path)s',
                 '--enable-multiarch', '--disable-multilib', '--disable-nls', '--enable-lto', '--enable-objc-gc',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s'],
        {},
        ['make', '-j'],
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
            ('gcc-4.9.3-multiarch.diff', 2),
            ('gcc-mips-multiarch.diff', 1),
            ('gcc-4.9-libgcclink.diff', 1),
        ],
        False,
        ['aarch64'],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-static', '--enable-shared', '--enable-multiarch', '--disable-nls', '--disable-sjlj',
                 '--enable-objc-gc', '--enable-languages=c,c++,objc,obj-c++', '--disable-multilib',
                 '--with-sysroot=%(sysroot_path)s', '--with-build-sysroot=%(sysroot_path)s',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--program-prefix=%(target)s-', '--program-suffix=-4.9', '--enable-gold'],
        {
            'powerpc': ['--disable-multilib', '--disable-soft-float', '--with-float=hard'],
            'arm': ['--with-arch-directory=arm', '--with-arch=armv7-a', '--with-fpu=vfpv3-d16', '--with-float=hard', '--with-mode=thumb'],
            'mipsel': ['--with-endian=little', '--with-arch-directory=mipsel', '--with-arch-32=mips2', '--with-tune-32=mips32r2', '--with-fp-32=xx',],
            'mips': ['--with-arch-directory=mips', '--with-arch-32=mips2', '--with-tune-32=mips32r2', '--with-fp-32=xx',],
        },
        ['make', '-j', '16'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'gcc-5',
        [
            ('ftp://ftp.irisa.fr/pub/mirrors/gcc.gnu.org/gcc/releases/gcc-5.4.0/gcc-5.4.0.tar.bz2', '', None)
        ],
        [
            ('gcc-4.9.2.patch', 2),
            ('gcc-5-multiarch.diff', 2),
            ('gcc-mips-multiarch.diff', 1),
            ('gcc-4.9-libgcclink.diff', 1),
            ('gcc-5-responsefile.diff', 1),
        ],
        False,
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-shared', '--enable-multiarch', '--disable-nls', '--disable-sjlj',
                 '--enable-objc-gc', '--enable-languages=c,c++,objc,obj-c++',
                 '--with-sysroot=%(sysroot_path)s', '--with-build-sysroot=%(sysroot_path)s', '--disable-multilib',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--program-prefix=%(target)s-', '--program-suffix=-5', '--enable-gold'],
        {
            'powerpc': ['--disable-multilib', '--disable-soft-float', '--with-float=hard'],
            'arm': ['--with-arch-directory=arm', '--with-arch=armv7-a', '--with-fpu=vfpv3-d16', '--with-float=hard', '--with-mode=thumb'],
            'mipsel': ['--with-endian=little', '--with-arch-directory=mipsel', '--with-arch-32=mips32r2', '--with-fp-32=xx', '--disable-libitm', '--disable-libsanitizer', '--disable-libquadmath', ],
            'mips': ['--with-arch-directory=mips', '--with-arch-32=mips32r2', '--with-fp-32=xx', '--disable-libitm', '--disable-libsanitizer', '--disable-libquadmath', ],
        },
        ['make', '-j', '16'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'gcc-6',
        [
            ('ftp://ftp.irisa.fr/pub/mirrors/gcc.gnu.org/gcc/releases/gcc-6.1.0/gcc-6.1.0.tar.bz2', '', None)
        ],
        [
            ('gcc-4.9.2.patch', 2),
            ('gcc-5-multiarch.diff', 2),
            ('gcc-mips-multiarch.diff', 1),
            ('gcc-4.9-libgcclink.diff', 1),
            ('gcc-5-responsefile.diff', 1),
        ],
        False,
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-static', '--enable-shared', '--enable-multiarch', '--disable-nls', '--disable-sjlj',
                 '--enable-objc-gc', '--enable-languages=c,c++,objc,obj-c++',
                 '--with-sysroot=%(sysroot_path)s', '--with-build-sysroot=%(sysroot_path)s', '--disable-multilib',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--program-prefix=%(target)s-', '--program-suffix=-6', '--enable-gold'],
        {
            'powerpc': ['--disable-multilib', '--disable-soft-float', '--with-float=hard'],
            'arm': ['--with-arch-directory=arm', '--with-arch=armv7-a', '--with-fpu=vfpv3-d16', '--with-float=hard', '--with-mode=thumb'],
            'mipsel': ['--with-endian=little', '--with-arch-directory=mipsel', '--with-arch-32=mips2', '--with-tune-32=mips32r2', '--with-fp-32=xx',],
            'mips': ['--with-arch-directory=mips', '--with-arch-32=mips2', '--with-tune-32=mips32r2', '--with-fp-32=xx',],
        },
        ['make', '-j', '16'],
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
            ('llvm-3.4.patch', 1)
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2012)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.4/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=x86_64-%(target_abi)s', '-DLLVM_TARGET_ARCH=x86_64',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
    ),
    (
        'clang-3.5',
        [
            ('http://llvm.org/releases/3.5.2/llvm-3.5.2.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.5.2/cfe-3.5.2.src.tar.xz', 'llvm-3.5.2.src/tools', 'clang'),
            ('http://llvm.org/releases/3.5.2/compiler-rt-3.5.2.src.tar.xz', 'llvm-3.5.2.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.5.patch', 1)
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2012)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.5/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=x86_64-%(target_abi)s', '-DLLVM_TARGET_ARCH=x86_64',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
    ),
    (
        'clang-3.6',
        [
            ('http://llvm.org/releases/3.6.2/llvm-3.6.2.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.6.2/cfe-3.6.2.src.tar.xz', 'llvm-3.6.2.src/tools', 'clang'),
            ('http://llvm.org/releases/3.6.2/compiler-rt-3.6.2.src.tar.xz', 'llvm-3.6.2.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.6.patch', 1)
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2012)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.6/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=x86_64-%(target_abi)s', '-DLLVM_TARGET_ARCH=x86_64',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
    ),
    (
        'clang-3.7',
        [
            ('http://llvm.org/releases/3.7.1/llvm-3.7.1.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.7.1/cfe-3.7.1.src.tar.xz', 'llvm-3.7.1.src/tools', 'clang'),
            ('http://llvm.org/releases/3.7.1/compiler-rt-3.7.1.src.tar.xz', 'llvm-3.7.1.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.7.patch', 1)
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2013)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.7/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=x86_64-%(target_abi)s', '-DLLVM_TARGET_ARCH=x86_64',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
    ),
    (
        'clang-3.8',
        [
            ('http://llvm.org/releases/3.8.0/llvm-3.8.0.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.8.0/cfe-3.8.0.src.tar.xz', 'llvm-3.8.0.src/tools', 'clang'),
            ('http://llvm.org/releases/3.8.0/compiler-rt-3.8.0.src.tar.xz', 'llvm-3.8.0.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.8.patch', 1)
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2013)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.8/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=x86_64-%(target_abi)s', '-DLLVM_TARGET_ARCH=x86_64',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else []),
    ),
    (
        'gdb',
        [
            ('http://ftp.gnu.org/gnu/gdb/gdb-7.11.tar.xz', '', None)
        ],
        [],
        True,
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=x86_64-%(target_abi)s', '--prefix=%(install_path)s',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--with-python=%(install_path)s/', '--enable-targets=all'],
        {},
        ['make', '-j8'],
        ['bash', '-c', 'make', 'install', '&&', 'make', 'install-strip-gdb'],
        ['make', 'clean'],
    ),
]


def hash(lst):
    m = md5()
    m.update(str(lst).encode())
    return m.hexdigest()

    
def up_to_date(sig, target_platform, pkg, step, arch, directory):
    if directory and not os.path.isdir(directory):
        return False
    try:
        with open('cache/%s/%s-%s-%s.status' % (target_platform, pkg, arch and arch or 'any', step), 'r') as f:
            md5 = f.read()
            return md5 == hash(sig)
    except Exception:
        return False


def set_up_to_date(sig, target_platform, pkg, step, arch):
    with open('cache/%s/%s-%s-%s.status' % (target_platform, pkg, arch and arch or 'any', step), 'w') as f:
        f.write(hash(sig))


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


def extract_pkg(data, target_platform, dest, rename):
    tar = tarfile.open(fileobj=io.BytesIO(data))
    root = tar.next()
    root_dir = root.name.split('/')[0]
    tar.extractall('src/%s/%s' % (target_platform, dest))
    if rename:
        os.rename(os.path.join('src', target_platform, dest, root_dir), os.path.join('src', target_platform, dest, rename))
        root_dir = rename
    return os.path.join(target_platform, dest, root_dir)


def patch_pkg(src_root_dir, pkg, patch, patch_level):
    print('applying %s...' % patch)
    with open(os.path.join('patches', patch), 'rb') as patchfile:
        p = subprocess.Popen(['patch', '--verbose', '--no-backup-if-mismatch', '-p', str(patch_level)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             cwd=src_root_dir)
        p.stdin.write(patchfile.read())
        out, err = p.communicate()
        p.stdin.close()
        if not isinstance(out, str):
            out = out.decode(sys.stdout.encoding, errors='ignore')
        if p.returncode != 0:
            raise Exception('failed to patch: %s' % out)
        with open('bld/%s-%s.log'%(pkg, patch), 'w') as logfile:
            logfile.write(out)


def run(sig, target_platform, pkg, arch, command, bld_dir, step, config):
    sig = sig + [command]
    if not up_to_date(sig, target_platform, pkg, step, arch, bld_dir):
        make_dir(bld_dir)
        print('running %s step...' % step)
        with open('bld/%s.log'%step, 'w') as logfile:
            run_command = [i % config for i in command]
            p = subprocess.Popen(run_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=bld_dir, env=env)
            line=p.stdout.readline()
            while line:
                if not isinstance(line, str):
                    line = line.decode(sys.stdout.encoding, errors='ignore')
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
            set_up_to_date(sig, target_platform, pkg, step, arch)
    return sig


def build(pkg, target_platform, src_dir, bld_dir, arch, abi, configure_cmd, build_cmd, install_cmd, clean_cmd, sig):
    if arch:
        config['arch'] = arch
        config['target'] = abi
    config['src_path'] = os.path.relpath(src_dir, bld_dir).replace('\\', '/') #'../../../%s' % src_dir
    make_dir(bld_root_dir)
    if configure_cmd:
        sig = run(sig, target_platform, pkg, arch, configure_cmd, bld_dir, 'configure', config)
    if build_cmd:
        sig = run(sig, target_platform, pkg, arch, build_cmd, bld_dir, 'build', config)
    if install_cmd:
        sig = run(sig, target_platform, pkg, arch, install_cmd, bld_dir, 'install', config)
    if clean_cmd:
        sig = run(sig, target_platform, pkg, arch, clean_cmd, bld_dir, 'clean', config)


if __name__ == '__main__':
    for target_platform, target_abi in target_platforms:
        config = {
            'install_path': os.path.abspath('pc-%s' % target_platform).replace('\\', '/'),
            'sysroot_path': os.path.abspath('pc-%s/sysroot' % target_platform).replace('\\', '/'),
            'host':         get_gcc_host(),
            'os':           sys.platform,
            'target_abi':   target_abi,
            'python':       'python.exe' if sys.platform == 'win32' else 'python',
            'gcc':          gcc,
            'gxx':          gxx,
            'build_2012':  'Visual Studio 11 2012 Win64'if sys.platform == 'win32' else 'Unix Makefiles',
            'build_2013':  'Visual Studio 12 2013 Win64'if sys.platform == 'win32' else 'Unix Makefiles',
        }
        all_archs = get_supported_archs(target_platform, config['sysroot_path'])
        print('%s - %s' % (target_platform, all_archs))
        do_build = sys.argv[1:]
        make_dir('cache/%s' % target_platform)
        make_dir('src/%s' % target_platform)
        make_dir('bld/%s' % target_platform)

        for package_name, package_urls, patch_list, is_host_build, skip_archs, configure_cmd, configure_extra_cmd, build_cmd, install_cmd, clean_cmd in packages:
            if do_build and package_name not in do_build:
                continue

            src_root_dir = 'src/%s/%s' % (target_platform, package_name)
            archs = [(None, None)] if is_host_build else all_archs

            for arch, abi in archs:
                if arch in skip_archs:
                    continue
                configure_arch_cmd = configure_extra_cmd.get(arch, [])
                sig = [['wget'] + package_urls, ['patch'] + patch_list,
                       configure_cmd + configure_arch_cmd,
                       build_cmd,
                       install_cmd]
                if arch:
                    bld_root_dir = os.path.abspath('bld/%s/%s-%s' % (target_platform, package_name, arch))
                else:
                    bld_root_dir = os.path.abspath('bld/%s/%s' % (target_platform, package_name))
                done  = up_to_date(sig, target_platform, package_name, 'install', arch, None)
                if not done:
                    print('=> building %s%s' % (package_name, ' for %s'%arch if arch else ''))
                    sig = [['wget'] + package_urls, ['patch'] + patch_list]
                    done = up_to_date(sig, target_platform, package_name, 'unpack', None, src_root_dir)
                    if not done:
                        del_dir(src_root_dir)
                        del_dir(bld_root_dir)
                        root_dir = None
                        if package_urls:
                            for url, dest, rename in package_urls:
                                data = download_pkg(url)
                                root_dir_pkg = extract_pkg(data, target_platform, dest, rename)
                                root_dir = root_dir or root_dir_pkg
                            os.rename('src/%s' % root_dir, 'src/%s/%s' % (target_platform, package_name))
                            for patch, patch_level in patch_list:
                                patch_pkg(src_root_dir, package_name, patch, patch_level)
                        else:
                            make_dir(src_root_dir)
                        set_up_to_date(sig, target_platform, package_name, 'unpack', None)
                    build(package_name, target_platform, src_root_dir, bld_root_dir, arch, abi,
                          configure_cmd + configure_extra_cmd.get(arch, []), build_cmd, install_cmd, clean_cmd,
                          sig)
                    #del_dir(bld_root_dir)
            #del_dir(src_root_dir)


