pushd `dirname $BASH_SOURCE`

tar xjf ../pkg/gmp-6.0.0a.tar.bz2
tar xJf ../pkg/mpfr-3.1.2.tar.xz
tar xzf ../pkg/mpc-1.0.2.tar.gz

tar xjf ../pkg/binutils-2.24.tar.bz2
pushd binutils-2.24
patch -p 2 < ../../patches/binutils-2.24.patch
popd

tar xJf ../pkg/gdb-7.8.1.tar.xz

tar xjf ../pkg/gcc-4.9.2.tar.bz2
pushd gcc-4.9.2
patch -p 2 < ../../patches/gcc-4.9.2.patch
popd

tar xJf ../pkg/llvm-3.5.0.src.tar.xz
pushd llvm-3.5.0.src/projects
tar xJf ../../../pkg/compiler-rt-3.5.0.src.tar.xz
mv compiler-rt-3.5.0.src compiler-rt
popd
pushd llvm-3.5.0.src/tools
tar xJf ../../../pkg/cfe-3.5.0.src.tar.xz
# Need to unpack twice to fix link issues
tar xJf ../../../pkg/cfe-3.5.0.src.tar.xz
mv cfe-3.5.0.src clang
popd
pushd llvm-3.5.0.src
patch -p 1 < ../../patches/llvm-3.5.0.patch

popd
