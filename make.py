GCC_MIRROR='ftp://ftp.mpi-sb.mpg.de/pub/gnu/mirror/gcc.gnu.org/pub/gcc'

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

target_paths = (
    #'pc-freebsd-i386',
    #'pc-freebsd-amd64',
    #'pc-freebsd-ppc',
    #'pc-freebsd-ppc64',
    'pc-freebsd-aarch64',
    #'pc-linux-gnu',
)

platform_flags = {
    'darwin':   [],
    'win32':    [],
}
global_env = os.environ.copy()
if 'CC' in global_env:
    gcc = global_env['CC']
    gxx = global_env['CXX']
elif sys.platform == 'win32':
    gcc = 'gcc'
    gxx = 'g++'
else:
    gcc='clang -fbracket-depth=1024'
    gxx='clang++ -fbracket-depth=1024'
    global_env['CC'] = gcc
    global_env['CXX'] = gxx
global_env['CFLAGS']   = ' '.join(platform_flags.get(sys.platform, []) + [global_env.get('CFLAGS', '')])
global_env['CXXFLAGS'] = ' '.join(platform_flags.get(sys.platform, []) + [global_env.get('CXXFLAGS', '')])
global_env['LDFLAGS']  = ' '.join(platform_flags.get(sys.platform, []) + [global_env.get('LDFLAGS', '')])
#global_env['CFLAGS_FOR_TARGET']   = ' '.join(['-O1', '-g'] + [env.get('CFLAGS_FOR_TARGET', '')])
#global_env['CXXFLAGS_FOR_TARGET']   = ' '.join(['-O1', '-g'] + [env.get('CXXFLAGS_FOR_TARGET', '')])
#global_env['LDFLAGS_FOR_TARGET']   = ' '.join(['-g', '-v'] + [env.get('LDFLAGS_FOR_TARGET', '')])
for target_path in target_paths:
    global_env['PATH'] = global_env['PATH'] + os.pathsep + os.path.abspath('%s/bin' % target_path).replace('\\', '/')


def get_arch(file):
    machines = {
        'PowerPC64':                        ('powerpc64', 'ppc64el'),
        'PowerPC':                          ('powerpc', 'ppcel'),
        'Intel 80386':                      ('', 'i386'),
        'Advanced Micro Devices X86-64':    ('', 'x86_64'),
        'AArch64':                          ('aarch64_be', 'aarch64'),
        'ARM':                              ('arm', 'armel'),
        'MIPS R3000':                       ('mips', 'mipsel'),
    }
    env = os.environ.copy()
    env['LC_ALL'] = 'C'
    p = subprocess.Popen(['readelf', '-h', file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    out, err = p.communicate()
    if not isinstance(out, str):
        out = out.decode(sys.stdout.encoding, errors='ignore')
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('Machine:'):
            machine = line[len('Machine:'):].strip()
        if line.startswith('Data:'):
            data = line[len('Data:'):].split(',')[1].strip()
    return machines[machine][1 if data == 'little endian' else 0]


def get_supported_archs(sysroot):
    result = []
    if os.path.isfile(os.path.join(sysroot, 'lib/ld-linux.so.2')):
        target_platform = 'linux-gnu'
        target_abi = 'linux-gnu'
        target_arch = 'x86_64'
        target_multiarch = True
        try:
            all_files = os.listdir(os.path.join(sysroot, 'lib'))
        except OSError:
            raise Exception("Is sysroot installed in %s?" % sysroot)
        else:
            for l in all_files:
                if l.find('linux-gnu') > 0 and os.path.isdir(os.path.join(sysroot, 'lib', l)):
                    arch = l.split('-')[0]
                    result.append((arch, l, [], {}))
    elif os.path.isfile(os.path.join(sysroot, 'bin/freebsd-version')):
        p = subprocess.Popen(['sh', os.path.join(sysroot, 'bin/freebsd-version')], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, err = p.communicate()
        if not isinstance(out, str):
            out = out.decode(sys.stdout.encoding, errors='ignore')
        out = out[:out.find('.')]
        target_platform = 'freebsd'
        target_arch = get_arch(os.path.join(sysroot, 'usr/lib/crt1.o'))
        target_abi = 'pc-freebsd%s.0' % (out)
        target_multiarch = False
        if os.path.isfile(os.path.join(sysroot, 'usr/lib32/crt1.o')):
            arch = get_arch(os.path.join(sysroot, 'usr/lib32/crt1.o'))
            abi = 'pc-freebsd%s.0' % (out)
            if not os.path.isfile('bld/lib32.h'):
                with open('bld/lib32.h', 'w') as f:
                    f.write('#define STANDARD_STARTFILE_PREFIX_1 "/lib32/"\n')
                    f.write('#define STANDARD_STARTFILE_PREFIX_2 "/usr/lib32/"\n')
            result.append((arch, arch + '-' + abi,
                           ['--with-lib-path==/lib32:=/usr/lib32:=/usr/local/lib32',
                            'CFLAGS=-include %s' % os.path.abspath('bld/lib32.h').replace('\\', '/'),
                            'CXXFLAGS=-include %s' % os.path.abspath('bld/lib32.h').replace('\\', '/')], {}))
        result.append((target_arch, target_arch + '-' + target_abi, [], {}))
    else:
        raise Exception("Don't know how to read supported archs for target %s" % sysroot)
    return target_platform, target_abi, target_arch, target_multiarch, result


def get_gcc_host():
    cmd = gcc.split() + ['-v']
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
            ('http://ftp.gnu.org/gnu/gmp/gmp-6.1.2.tar.bz2', '', None),
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
            ('http://www.mpfr.org/mpfr-current/mpfr-3.1.5.tar.xz', '', None),
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
            ('ftp://ftp.gnu.org/gnu/mpc/mpc-1.0.3.tar.gz', '', None),
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
            ('http://ftp.gnu.org/gnu/binutils/binutils-2.29.tar.bz2', '', None)
        ],
        [
            ('binutils-2.24.patch', 1),
        ],
        False,
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-static', '--disable-shared', '--enable-gold', '--with-sysroot=%(sysroot_path)s', '--disable-werror',
                 '%(multiarch)s', '--disable-multilib', '--disable-nls', '--enable-lto', '--enable-objc-gc',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s'],
        {},
        ['make', '-j'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'gcc-4.9',
        [
            ('%s/releases/gcc-4.9.4/gcc-4.9.4.tar.bz2' % GCC_MIRROR, '', None)
        ],
        [
            ('gcc-4.9.2.patch', 2),
            ('gcc-4.9.3-multiarch.diff', 2),
            ('gcc-mips-multiarch.diff', 1),
            ('gcc-4.9-libgcclink.diff', 1),
        ],
        False,
        [re.compile('aarch64-.*')],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-static', '--enable-shared', '%(multiarch)s', '--disable-nls', '--disable-sjlj',
                 '--enable-objc-gc', '--enable-languages=c,c++,objc,obj-c++', '--disable-multilib',
                 '--with-sysroot=%(sysroot_path)s', '--with-build-sysroot=%(sysroot_path)s',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--program-prefix=%(target)s-', '--program-suffix=-4.9', '--enable-gold'],
        {
            'aarch64': (['--enable-fix-cortex-a53-835769', '--enable-fix-cortex-a53-843419'], {}),
            'powerpc': (['--disable-multilib', '--disable-soft-float', '--with-float=hard'], {}),
            'arm': (['--with-arch-directory=arm', '--with-arch=armv7-a', '--with-fpu=vfpv3-d16', '--with-float=hard', '--with-mode=thumb', ], {}),
            'mipsel': (['--with-endian=little', '--with-arch-directory=mipsel', '--with-arch-32=mips2', '--with-tune-32=mips32r2', '--with-fp-32=xx',], {'CFLAGS_FOR_TARGET':'-O1 -g', 'CXXFLAGS_FOR_TARGET': '-O1 -g'}),
            'mips': (['--with-arch-directory=mips', '--with-arch-32=mips2', '--with-tune-32=mips32r2', '--with-fp-32=xx',], {'CFLAGS_FOR_TARGET':'-O1 -g', 'CXXFLAGS_FOR_TARGET': '-O1 -g'}),
        },
        ['make', '-j', '16'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'gcc-5',
        [
            ('%s/releases/gcc-5.4.0/gcc-5.4.0.tar.bz2' % GCC_MIRROR, '', None)
        ],
        [
            ('gcc-4.9.2.patch', 2),
            ('gcc-5-multiarch.diff', 2),
            ('gcc-mips-multiarch.diff', 1),
            ('gcc-4.9-libgcclink.diff', 1),
            ('gcc-5-responsefile.diff', 1),
        ],
        False,
        [re.compile('aarch64-.*-freebsd.*')],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-shared', '%(multiarch)s', '--disable-nls', '--disable-sjlj',
                 '--enable-objc-gc', '--enable-languages=c,c++,objc,obj-c++',
                 '--with-sysroot=%(sysroot_path)s', '--with-build-sysroot=%(sysroot_path)s', '--disable-multilib',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--program-prefix=%(target)s-', '--program-suffix=-5', '--enable-gold'],
        {
            'aarch64': (['--enable-fix-cortex-a53-835769', '--enable-fix-cortex-a53-843419'], {}),
            'powerpc': (['--disable-multilib', '--disable-soft-float', '--with-float=hard'], {}),
            'arm': (['--with-arch-directory=arm', '--with-arch=armv7-a', '--with-fpu=vfpv3-d16', '--with-float=hard', '--with-mode=thumb'], {}),
            'mipsel': (['--with-endian=little', '--with-arch-directory=mipsel', '--with-arch-32=mips32r2', '--with-fp-32=xx', '--disable-libitm', '--disable-libsanitizer', '--disable-libquadmath', ], {'CFLAGS_FOR_TARGET':'-O0 -g', 'CXXFLAGS_FOR_TARGET': '-O0 -g'}),
            'mips': (['--with-arch-directory=mips', '--with-arch-32=mips32r2', '--with-fp-32=xx', '--disable-libitm', '--disable-libsanitizer', '--disable-libquadmath', ], {'CFLAGS_FOR_TARGET':'-O0 -g', 'CXXFLAGS_FOR_TARGET': '-O0 -g'}),
        },
        ['make', '-j', '16'],
        ['make', 'install-strip'],
        ['make', 'clean'],
    ),
    (
        'gcc-6',
        [
            ('%s/releases/gcc-6.4.0/gcc-6.4.0.tar.gz' % GCC_MIRROR, '', None)
        ],
        [
            ('gcc-4.9.2.patch', 2),
            ('gcc-6-multiarch.diff', 2),
            ('gcc-mips-multiarch.diff', 1),
            ('gcc-4.9-libgcclink.diff', 1),
            ('gcc-5-responsefile.diff', 1),
        ],
        False,
        [re.compile('aarch64-.*-freebsd.*')],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target)s', '--prefix=%(install_path)s',
                 '--enable-shared', '%(multiarch)s', '--disable-nls', '--disable-sjlj',
                 '--enable-objc-gc', '--enable-languages=c,c++,objc,obj-c++',
                 '--with-sysroot=%(sysroot_path)s', '--with-build-sysroot=%(sysroot_path)s', '--disable-multilib',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--program-prefix=%(target)s-', '--program-suffix=-6', '--enable-gold'],
        {
            'aarch64': (['--enable-fix-cortex-a53-835769', '--enable-fix-cortex-a53-843419'], {}),
            'powerpc': (['--disable-multilib', '--disable-soft-float', '--with-float=hard'], {}),
            'arm': (['--with-arch-directory=arm', '--with-arch=armv7-a', '--with-fpu=vfpv3-d16', '--with-float=hard', '--with-mode=thumb'], {}),
            'mipsel': (['--with-endian=little', '--with-arch-directory=mipsel', '--with-arch-32=mips2', '--with-tune-32=mips32r2', '--with-fp-32=xx', '--disable-libitm', '--disable-libsanitizer', '--disable-libquadmath', ], {'CFLAGS_FOR_TARGET':'-O1 -g', 'CXXFLAGS_FOR_TARGET': '-O1 -g'}),
            'mips': (['--with-arch-directory=mips', '--with-arch-32=mips2', '--with-tune-32=mips32r2', '--with-fp-32=xx', '--disable-libitm', '--disable-libsanitizer', '--disable-libquadmath', ], {'CFLAGS_FOR_TARGET':'-O1 -g', 'CXXFLAGS_FOR_TARGET': '-O1 -g'}),
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
            ('llvm-3.4.patch', 1),
            ('clang-3.4-freebsd-crosscompile.diff', 1),
            ('llvm-3.4-execute.diff', 1),
            ('clang-3.4-include-path.diff', 1),
            ('clang-3.4-lib-path.diff', 1),
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2012)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.4/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=%(target_arch)s-%(target_abi)s', '-DLLVM_TARGET_ARCH=%(target_arch)s',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--','-j', '16']),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
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
            ('llvm-3.5.patch', 1),
            ('clang-freebsd-crosscompile.diff', 1),
            ('llvm-3.4-execute.diff', 1),
            ('clang-3.5-include-path.diff', 1),
            ('clang-3.4-lib-path.diff', 1),
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2012)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.5/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=%(target_arch)s-%(target_abi)s', '-DLLVM_TARGET_ARCH=%(target_arch)s',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
    ),
    (
        'clang-3.6',
        [
            ('http://llvm.org/releases/3.6.2/llvm-3.6.2.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.6.2/cfe-3.6.2.src.tar.xz', 'llvm-3.6.2.src/tools', 'clang'),
            ('http://llvm.org/releases/3.6.2/compiler-rt-3.6.2.src.tar.xz', 'llvm-3.6.2.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.6.patch', 1),
            ('clang-freebsd-crosscompile.diff', 1),
            ('llvm-3.6-execute.diff', 1),
            ('clang-3.5-include-path.diff', 1),
            ('clang-3.4-lib-path.diff', 1),
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2012)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.6/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=%(target_arch)s-%(target_abi)s', '-DLLVM_TARGET_ARCH=%(target_arch)s',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
    ),
    (
        'clang-3.7',
        [
            ('http://llvm.org/releases/3.7.1/llvm-3.7.1.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.7.1/cfe-3.7.1.src.tar.xz', 'llvm-3.7.1.src/tools', 'clang'),
            ('http://llvm.org/releases/3.7.1/compiler-rt-3.7.1.src.tar.xz', 'llvm-3.7.1.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.7.patch', 1),
            ('clang-freebsd-crosscompile.diff', 1),
            ('llvm-3.6-execute.diff', 1),
            ('clang-3.7-include-path.diff', 1),
            ('clang-3.4-lib-path.diff', 1),
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2013)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.7/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=%(target_arch)s-%(target_abi)s', '-DLLVM_TARGET_ARCH=%(target_arch)s',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
    ),
    (
        'clang-3.8',
        [
            ('http://llvm.org/releases/3.8.1/llvm-3.8.1.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.8.1/cfe-3.8.1.src.tar.xz', 'llvm-3.8.1.src/tools', 'clang'),
            ('http://llvm.org/releases/3.8.1/compiler-rt-3.8.1.src.tar.xz', 'llvm-3.8.1.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.8.patch', 1),
            ('clang-3.7-include-path.diff', 1),
            ('clang-3.8-lib-path.diff', 1),
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2013)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.8/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=%(target_arch)s-%(target_abi)s', '-DLLVM_TARGET_ARCH=%(target_arch)s',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
    ),
    (
        'clang-3.9',
        [
            ('http://llvm.org/releases/3.9.1/llvm-3.9.1.src.tar.xz', '', None),
            ('http://llvm.org/releases/3.9.1/cfe-3.9.1.src.tar.xz', 'llvm-3.9.1.src/tools', 'clang'),
            ('http://llvm.org/releases/3.9.1/compiler-rt-3.9.1.src.tar.xz', 'llvm-3.9.1.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-3.9.patch', 1),
            ('clang-3.7-include-path.diff', 1),
            ('clang-3.8-lib-path.diff', 1),
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2013)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-3.9/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=%(target_arch)s-%(target_abi)s', '-DLLVM_TARGET_ARCH=%(target_arch)s',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
    ),
    (
        'clang-4.0',
        [
            ('http://llvm.org/releases/4.0.1/llvm-4.0.1.src.tar.xz', '', None),
            ('http://llvm.org/releases/4.0.1/cfe-4.0.1.src.tar.xz', 'llvm-4.0.1.src/tools', 'clang'),
            ('http://llvm.org/releases/4.0.1/compiler-rt-4.0.1.src.tar.xz', 'llvm-4.0.1.src/projects', 'compiler-rt'),
        ],
        [
            ('llvm-4.0.patch', 1),
            ('clang-3.7-include-path.diff', 1),
            ('clang-3.8-lib-path.diff', 1),
        ],
        True,
        [],
        ['cmake', '%(src_path)s', '-G', '%(build_2013)s', '-DCMAKE_INSTALL_PREFIX=%(install_path)s/lib/llvm-4.0/',
                  '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=0', '-DDEFAULT_SYSROOT=%(sysroot_path)s',
                  '-DLLVM_DEFAULT_TARGET_TRIPLE=%(target_arch)s-%(target_abi)s', '-DLLVM_TARGET_ARCH=%(target_arch)s',
                  '-DGCC_INSTALL_PREFIX=%(install_path)s/', '-DPYTHON_EXECUTABLE=%(install_path)s/bin/%(python)s',
                  '-DLLVM_INSTALL_TOOLCHAIN_ONLY=1',],
        {},
        ['cmake', '--build', '.'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'install'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
        ['cmake', '--build', '.', '--target', 'clean'] + (['--', '/p:Configuration=Release'] if sys.platform == 'win32' else ['--', '-j', '16']),
    ),
    (
        'gdb',
        [
            ('http://ftp.gnu.org/gnu/gdb/gdb-7.11.tar.xz', '', None)
        ],
        [],
        True,
        [],
        ['bash', '%(src_path)s/configure', '--build=%(host)s', '--target=%(target_arch)s-%(target_abi)s', '--prefix=%(install_path)s',
                 '--with-gmp=%(install_path)s', '--with-mpfr=%(install_path)s', '--with-mpc=%(install_path)s',
                 '--with-python=%(install_path)s/', '--enable-targets=all', '--program-prefix='],
        {},
        ['make', '-j8'],
        ['bash', '-c', 'make install && make install-strip-gdb'],
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


def run(sig, target_platform, pkg, arch, command, env, bld_dir, step, config):
    sig = sig + [command]
    v = global_env.copy()
    for k, i in env.items():
        if k in v:
            v[k] = v[k] + ' ' + env[k]
        else:
            v[k] = env[k]
    if not up_to_date(sig, target_platform, pkg, step, arch, bld_dir):
        make_dir(bld_dir)
        print('running %s step...' % step)
        with open('bld/%s.log'%step, 'w') as logfile:
            run_command = [i % config for i in command]
            p = subprocess.Popen(run_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=bld_dir, env=v)
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


def build(pkg, target_platform, src_dir, bld_dir, arch, abi, configure_cmd, configure_env, build_cmd, install_cmd, clean_cmd, sig):
    if arch:
        config['arch'] = arch
        config['target'] = abi
    config['src_path'] = os.path.relpath(src_dir, bld_dir).replace('\\', '/') #'../../../%s' % src_dir
    make_dir(bld_root_dir)
    if configure_cmd:
        sig = run(sig, target_platform, pkg, arch, configure_cmd, configure_env, bld_dir, 'configure', config)
    if build_cmd:
        sig = run(sig, target_platform, pkg, arch, build_cmd, {}, bld_dir, 'build', config)
    if install_cmd:
        sig = run(sig, target_platform, pkg, arch, install_cmd, {}, bld_dir, 'install', config)
    if clean_cmd:
        sig = run(sig, target_platform, pkg, arch, clean_cmd, {}, bld_dir, 'clean', config)


if __name__ == '__main__':
    make_dir('bld')
    for target_path in target_paths:
        sysroot = '%s/sysroot' % target_path
        target_platform, target_abi, target_arch, target_multiarch, all_archs = get_supported_archs(sysroot)

        config = {
            'install_path': os.path.abspath(target_path).replace('\\', '/'),
            'sysroot_path': os.path.abspath(sysroot).replace('\\', '/'),
            'host':         get_gcc_host(),
            'os':           sys.platform,
            'target_abi':   target_abi,
            'target_arch':  target_arch,
            'multiarch':    '--enable-multiarch' if target_multiarch else '--disable-multiarch',
            'python':       'python.exe' if sys.platform == 'win32' else 'python',
            'gcc':          gcc,
            'gxx':          gxx,
            'build_2012':  'Visual Studio 11 2012 Win64'if sys.platform == 'win32' else 'Unix Makefiles',
            'build_2013':  'Visual Studio 12 2013 Win64'if sys.platform == 'win32' else 'Unix Makefiles',
        }

        print('%s - %s' % (target_platform, all_archs))
        do_build = sys.argv[1:]
        make_dir('cache/%s' % target_path)
        make_dir('src/%s' % target_path)
        make_dir('bld/%s' % target_path)

        for package_name, package_urls, patch_list, is_host_build, skip_archs, configure_cmd, configure_extra, build_cmd, install_cmd, clean_cmd in packages:
            if do_build and package_name not in do_build:
                continue

            src_root_dir = 'src/%s/%s' % (target_path, package_name)
            archs = [(None, None, [], {})] if is_host_build else all_archs

            for arch, abi, arch_config, arch_env in archs:
                for p in skip_archs:
                    if p.match(arch):
                        break
                    if p.match(abi):
                        break
                else:
                    configure_extra_cmd, configure_extra_env = configure_extra.get(arch, ([], {}))
                    extra_env = {}
                    extra_env.update(configure_extra_env)
                    extra_env.update(arch_env)
                    sig = [['wget'] + package_urls, ['patch'] + patch_list,
                           configure_cmd + configure_extra_cmd + arch_config,
                           build_cmd,
                           install_cmd]
                    if arch:
                        bld_root_dir = os.path.abspath('bld/%s/%s-%s' % (target_path, package_name, arch))
                    else:
                        bld_root_dir = os.path.abspath('bld/%s/%s' % (target_path, package_name))
                    done  = up_to_date(sig, target_path, package_name, 'install', arch, None)
                    if not done:
                        print('=> building %s%s' % (package_name, ' for %s'%arch if arch else ''))
                        sig = [['wget'] + package_urls, ['patch'] + patch_list]
                        done = up_to_date(sig, target_path, package_name, 'unpack', None, src_root_dir)
                        if not done:
                            del_dir(src_root_dir)
                            del_dir(bld_root_dir)
                            root_dir = None
                            if package_urls:
                                for url, dest, rename in package_urls:
                                    data = download_pkg(url)
                                    root_dir_pkg = extract_pkg(data, target_path, dest, rename)
                                    root_dir = root_dir or root_dir_pkg
                                os.rename('src/%s' % root_dir, 'src/%s/%s' % (target_path, package_name))
                                for patch, patch_level in patch_list:
                                    patch_pkg(src_root_dir, package_name, patch, patch_level)
                            else:
                                make_dir(src_root_dir)
                            set_up_to_date(sig, target_path, package_name, 'unpack', None)
                        build(package_name, target_path, src_root_dir, bld_root_dir, arch, abi,
                              configure_cmd + configure_extra_cmd + arch_config, extra_env, build_cmd, install_cmd, clean_cmd,
                              sig)
                        #del_dir(bld_root_dir)
            #del_dir(src_root_dir)
