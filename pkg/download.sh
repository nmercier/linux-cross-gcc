pushd `dirname $BASH_SOURCE`

function do_download {
	file=`basename $1`;
	rm -f $file;
	wget $1;
	if [ $? != 0 ]; then
		echo "Unable to download $file!"
		exit 1
	fi
}

do_download http://www.mpfr.org/mpfr-current/mpfr-3.1.2.tar.xz
do_download http://ftp.gnu.org/gnu/gmp/gmp-6.0.0a.tar.bz2
do_download ftp://ftp.gnu.org/gnu/mpc/mpc-1.0.2.tar.gz
do_download http://ftp.gnu.org/gnu/binutils/binutils-2.24.tar.bz2
do_download ftp://ftp.nluug.nl/mirror/languages/gcc/releases/gcc-4.9.2/gcc-4.9.2.tar.bz2
do_download http://ftp.gnu.org/gnu/gdb/gdb-7.8.1.tar.xz
do_download http://llvm.org/releases/3.5.0/cfe-3.5.0.src.tar.xz
do_download http://llvm.org/releases/3.5.0/llvm-3.5.0.src.tar.xz
do_download http://llvm.org/releases/3.5.0/compiler-rt-3.5.0.src.tar.xz

popd
