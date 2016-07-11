config={}
with open('etc/pkg/config', 'r') as config_file:
    exec(config_file.read(), config)
print('pkg for FreeBSD %s %s' % (config['DIST'], config['ARCHITECTURE'][1]))

import os
import subprocess
import sys
import re
import io
import shutil
import copy
try:
    import urllib2
except ImportError:
    from urllib import request as urllib2
import bz2, lzma
try:
    import cPickle as pickle
except ImportError:
    import pickle
import tarfile

try:
    from hashlib import md5
except ImportError:
    from md5 import md5

desc="""
pkg {base | -h}
"""


available_package_list_file = 'var/cache/pkg/package_available.pkl'
installed_package_list_file = 'var/cache/pkg/package_installed.pkl'
link_package_list_file = 'var/cache/pkg/package_links.pkl'
package_folder = 'var/cache/pkg/archives'


def usage():
    print(desc)
    

def download(url):
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
    chunk_size = 8192
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


def base():
    for pkg, required in [
        ('kernel.txz', True),
        ('base.txz', True),
        ('lib32.txz', False),
     ]:
        base_url = config['MIRROR'] + config['ARCHITECTURE'][0] + '/' + config['ARCHITECTURE'][1] + '/' + config['DIST'] + '/' + pkg
        if required or config['ARCHITECTURE'][2]:
            try:
                data = download(base_url)
            except Exception as e:
                if not optional:
                    raise e
            else:
                tar = tarfile.open(fileobj=io.BytesIO(data))
                for tarinfo in tar:
                    tarinfo = copy.copy(tarinfo)
                    tarinfo.mode = 0o700
                    try:
                        tar.extract(tarinfo, '.', set_attrs=False)
                    except ValueError as e:
                        print(e)
                    except OSError as e:
                        print(tarinfo.name)
                        os.unlink(tarinfo.name)
                        tar.extract(tarinfo, '.', set_attrs=False)

    def fix_links(dir):
        for l in os.listdir(dir):
            p = os.path.join(dir, l)
            if os.path.islink(p):
                target = p
                seen = set([target])
                while os.path.islink(target):
                    real = os.readlink(target)
                    parent = os.path.split(target)[0]
                    if real[0] == '/':
                        target = '.' + real
                    else:
                        target = os.path.join(parent, real)
                    if target in seen:
                        print ('recursive link: %s => %s' % (p, target))
                    seen.add(target)
                if os.path.exists(target):
                    print ('%s => %s' % (p, target))
                    os.unlink(p)
                    if os.path.isdir(target):
                        fix_links(target)
                        shutil.copytree(target, p)
                    else:
                        shutil.copy(target, p)
                else:
                    print('broken link: %s => %s' % (p, target))
                    os.unlink(p)
            elif os.path.isdir(p):
                fix_links(p)
    if sys.platform == 'win32':
        fix_links('.')


if __name__ == '__main__':
    command  = sys.argv[1]
    packages = sys.argv[2:]

    try:
        if command == '-h':
            usage()
        elif command == 'base':
            if packages:
                raise Exception(desc)
            base()
        else:
            raise Exception('unknown command: %s\n\n%s' % (command, desc))
    except Exception as e:
        print(e.__class__, e)
        exit(1)
    else:
        exit(0)
