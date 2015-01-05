prefix=`dirname $BASH_SOURCE`
prefix=`dirname $prefix`
prefix=`dirname $prefix`/x86_64-pc-linux-gnu

if [ ! -d $prefix ]; then mkdir $prefix; fi
pushd $prefix; prefix=`pwd`; popd
echo $prefix

pushd `dirname $BASH_SOURCE`

build() {
package=$1; shift
rm -rf $package; mkdir $package
pushd $package
echo configuring $package...
ABI=32 CC=gcc CXX=g++ CFLAGS="-static-libgcc" CXXFLAGS="-static-libgcc -static-libstdc++" ../../src/$package/configure --prefix=$prefix $@ > config.log
echo building $package...
make > make.log && make install-strip > install.log
popd
}

build_clang() {
package=$1; shift
rm -rf $package; mkdir $package
pushd $package
echo configuring $package...
ABI=32 CC=gcc CXX=g++ CFLAGS="-static-libgcc -DWINVER=0x600 -D_WIN32_WINNT=0x600" CXXFLAGS="-static-libgcc -static-libstdc++ -DWINVER=0x600 -D_WIN32_WINNT=0x600" ../../src/$package/configure --prefix=$prefix $@ > config.log
echo building $package...
make > make.log && make install > install.log
popd
}

build_gdb() {
package=$1; shift
rm -rf $package; mkdir $package
pushd $package
echo configuring $package...
ABI=32 CC=gcc CXX=g++ CFLAGS="-static-libgcc" CXXFLAGS="-static-libgcc -static-libstdc++" ../../src/$package/configure --prefix=$prefix $@ > config.log
echo building $package...
make > make.log && make install > install.log && make install-strip-gdb >> install.log
popd
}


#build gmp-6.0.0 --disable-shared --enable-static
#build mpfr-3.1.2 --disable-shared --enable-static --with-gmp=$prefix
#build mpc-1.0.2 --disable-shared --enable-static --with-gmp=$prefix --with-mpfr=$prefix
#build binutils-2.24 --target=x86_64-pc-linux-gnu --with-sysroot=$prefix/sysroot/ --with-build-sysroot=$prefix/sysroot/ \
#					--enable-multiarch --with-multilib-list=m32,m64,mx32 --disable-nls --enable-static --disable-sjlj \
#					--disable-win32-registry --enable-gold --with-gmp=$prefix --with-mpfr=$prefix --with-mpc=$prefix
#build gcc-4.9.2 --target=x86_64-pc-linux-gnu --with-sysroot=$prefix/sysroot/ --with-build-sysroot=$prefix/sysroot/ \
#				--enable-multiarch --with-multilib-list=m32,m64 --disable-nls --enable-static --disable-sjlj \
#				--disable-win32-registry --enable-gold --with-gmp=$prefix --with-mpfr=$prefix --with-mpc=$prefix \
#				--enable-objc-gc --enable-languages=c,c++,objc,obj-c++
#build_clang llvm-3.5.0.src --target=x86_64-pc-linux-gnu --enable-optimized=yes --enable-assertions=no \
#						   --enable-keep-symbols=no --enable-docs=no --program-prefix= --enable-targets=all \
#						   --with-sysroot=$prefix/sysroot --with-default-sysroot=$prefix/sysroot \
#						   --with-gcc-toolchain=$prefix
build_gdb gdb-7.8.1 --target=x86_64-pc-linux-gnu --with-gmp=$prefix --with-mpfr=$prefix --with-mpc=$prefix \
					--enable-multiarch --with-multilib-list=m32,m64 --disable-nls --enable-languages=c,c++,objc,obj-c++ \
					--enable-shared --enable-static --disable-sjlj --disable-win32-registry


popd

